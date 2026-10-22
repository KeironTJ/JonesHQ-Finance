from flask import abort, current_app, render_template, request, redirect, url_for, flash, jsonify
from flask_login import current_user
from sqlalchemy import func
from . import income_bp
from models.income import Income
from models.recurring_income import RecurringIncome
from models.accounts import Account
from models.categories import Category
from models.users import User
from services.finance.income_service import IncomeService, MAX_FORECAST_YEARS
from extensions import db
from datetime import datetime, date
from decimal import Decimal
from utils.db_helpers import family_query, family_get_or_404
from services.household.member_identity_service import MemberIdentityService
from services.planning.retirement_service import RetirementService


GENERIC_ERROR = 'Something went wrong — please try again.'


def _fail(error, fallback):
    """Roll back and flash a user-facing message. Only ValueErrors (raised by the
    service with a user-facing message) are shown verbatim; anything else is
    logged and replaced with a generic message so internals aren't exposed."""
    db.session.rollback()
    if isinstance(error, ValueError):
        flash(str(error) or fallback, 'danger')
    else:
        current_app.logger.exception(fallback)
        flash(f'{fallback} {GENERIC_ERROR}', 'danger')


def _income_categories():
    return (
        family_query(Category)
        .filter(func.lower(Category.category_type) == 'income')
        .order_by(Category.head_budget, Category.sub_budget)
        .all()
    )


def _parse_form_date(field, label):
    try:
        return datetime.strptime(request.form[field], '%Y-%m-%d').date()
    except (KeyError, ValueError):
        raise ValueError(f'{label} must be a valid date (YYYY-MM-DD).')


def _get_income_people():
    """Return a list of person names for income forms, sourced from active family members."""
    seen = set()
    people = []
    for member in family_query(User).filter(User.is_active == True).all():
        name = (member.member_name or member.name or '').strip()
        if name and name not in seen:
            seen.add(name)
            people.append(name)
    # Fall back to names already stored in the database
    if not people:
        rows = (
            family_query(Income).with_entities(Income.person).distinct()
            .union(family_query(RecurringIncome).with_entities(RecurringIncome.person).distinct())
            .all()
        )
        for row in rows:
            if row[0] and row[0] not in seen:
                seen.add(row[0])
                people.append(row[0])
    if 'Household' not in seen:
        people.append('Household')
    return people


@income_bp.route('/income')
def index():
    """List all income records — auto-generates missing records on load."""
    # Silently fill forecasts up to the forecast horizon
    try:
        IncomeService.generate_all_missing_income()
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Automatic income generation failed')

    # Get filter parameters
    person = request.args.get('person', None)
    year = request.args.get('year', None)

    # Get summary
    summary = IncomeService.get_income_summary(person=person, year=year)

    # Active recurring templates (shown as context on the page)
    templates_query = family_query(RecurringIncome).filter_by(is_active=True)
    if person:
        templates_query = templates_query.filter_by(person=person)
    recurring_templates = templates_query.order_by(RecurringIncome.person, RecurringIncome.source).all()

    # Get all accounts for the dropdown
    accounts = family_query(Account).filter_by(is_active=True).order_by(Account.name).all()

    # Get unique people and years for filters
    people = family_query(Income).with_entities(Income.person).distinct().order_by(Income.person).all()
    people = [p[0] for p in people] if people else _get_income_people()

    years = family_query(Income).with_entities(db.func.substr(Income.tax_year, 1, 4).label('year')).distinct().all()
    years = sorted([y[0] for y in years], reverse=True) if years else []

    # Expenses folded into each payslip's deposit, so the page can show what
    # actually makes up "take home + expenses" instead of just the total.
    from models.expenses import Expense
    from models.expense_reimbursement_group import ExpenseReimbursementGroup
    income_ids = [inc.id for inc in summary['records']]
    linked_expenses_by_income = {}
    if income_ids:
        for exp in family_query(Expense).filter(Expense.income_id.in_(income_ids)).order_by(Expense.date).all():
            linked_expenses_by_income.setdefault(exp.income_id, []).append(exp)

    folded_recurring_income_ids = {
        g.recurring_income_id
        for g in family_query(ExpenseReimbursementGroup).filter_by(mode='folded').all()
        if g.recurring_income_id
    }

    return render_template('income/index.html',
                           income_records=summary['records'],
                           summary=summary,
                           recurring_templates=recurring_templates,
                           accounts=accounts,
                           people=people,
                           years=years,
                           current_person=person,
                           current_year=year,
                           today=date.today(),
                           forecast_years=IncomeService.forecast_years(),
                           today_year=datetime.now().year,
                           linked_expenses_by_income=linked_expenses_by_income,
                           folded_recurring_income_ids=folded_recurring_income_ids)


@income_bp.route('/income/add', methods=['GET', 'POST'])
def add():
    """Add a new one-off income record"""
    if request.method == 'POST':
        try:
            income = IncomeService.create_one_off_income(request.form)
            flash(f'Income record added — take home £{income.take_home:,.2f}.', 'success')
            return redirect(url_for('income.index'))
        except Exception as e:
            _fail(e, 'Error adding income.')
            return redirect(url_for('income.add'))

    accounts = family_query(Account).filter_by(is_active=True).order_by(Account.name).all()
    return render_template('income/add.html', accounts=accounts, people=_get_income_people(),
                           member_options=MemberIdentityService.options())


@income_bp.route('/income/<int:id>/edit', methods=['GET', 'POST'])
def edit(id):
    """Edit an income record — supports both calculated and manual-override modes."""
    income = family_get_or_404(Income, id)

    if request.method == 'POST':
        try:
            income = IncomeService.update_income_record(id, request.form)
            flash(f'Income record updated — take home £{income.take_home:,.2f}.', 'success')
            return redirect(url_for('income.index'))
        except Exception as e:
            _fail(e, 'Error updating income.')
            income = family_get_or_404(Income, id)

    accounts = family_query(Account).filter_by(is_active=True).order_by(Account.name).all()
    return render_template('income/edit.html', income=income, accounts=accounts, people=_get_income_people(),
                           member_options=MemberIdentityService.options(income),
                           form=request.form if request.method == 'POST' else None)


@income_bp.route('/income/<int:id>/delete', methods=['POST'])
def delete(id):
    """Delete an income record"""
    keep_transaction = request.form.get('keep_transaction') == '1'
    try:
        IncomeService.delete_income_record(id, keep_transaction=keep_transaction)
        flash('Income record deleted successfully!', 'success')
    except Exception as e:
        _fail(e, 'Error deleting income.')
    return redirect(url_for('income.index'))


@income_bp.route('/income/delete-multiple', methods=['POST'])
def delete_multiple():
    """Delete multiple income records"""
    income_ids = request.form.getlist('income_ids')
    if not income_ids:
        flash('No income records selected.', 'warning')
        return redirect(url_for('income.index'))
    try:
        deleted_count = IncomeService.delete_income_records(income_ids)
        flash(f'Successfully deleted {deleted_count} income record(s) and their linked transactions.', 'success')
    except Exception as e:
        _fail(e, 'Error deleting income records.')
    return redirect(url_for('income.index'))


@income_bp.route('/income/toggle/<int:id>/paid', methods=['POST'])
def toggle_paid(id):
    """Toggle the is_paid flag for an income record"""
    family_get_or_404(Income, id)
    try:
        income = IncomeService.toggle_income_paid(id)
        return jsonify({'id': income.id, 'field': 'paid', 'value': income.is_paid})
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Failed to toggle income paid status')
        return jsonify({'error': 'Unable to record the payslip.'}), 500


@income_bp.route('/income/<int:id>/enter-actual', methods=['POST'])
def enter_actual(id):
    """Quick-entry of actual payslip figures for a generated income record."""
    family_get_or_404(Income, id)
    try:
        income = IncomeService.record_actual_payslip(id, request.form)
        flash(f'Actual payslip for {income.pay_date.strftime("%B %Y")} recorded — transaction updated.', 'success')
    except Exception as e:
        _fail(e, 'Error recording payslip.')
    return redirect(url_for('income.index'))


@income_bp.route('/income/calculate-preview', methods=['POST'])
def calculate_preview():
    """AJAX endpoint to preview tax/NI calculations"""
    try:
        result = IncomeService.preview_payslip(request.get_json(silent=True))
        return jsonify({'success': True, **result})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception:
        current_app.logger.exception('Income preview failed')
        return jsonify({'success': False, 'error': 'Unable to calculate the income preview.'}), 400


# ============= INCOME SOURCES =============

def _source_form_context(source=None):
    from models.pensions import Pension
    from services.finance import payroll_calculator as pc
    from services.finance import uk_tax_tables

    return dict(
        src=source,
        accounts=family_query(Account).filter_by(is_active=True).order_by(Account.name).all(),
        categories=_income_categories(),
        people=_get_income_people(),
        member_options=MemberIdentityService.options(source),
        pensions=family_query(Pension).filter_by(is_active=True).order_by(Pension.person, Pension.provider).all(),
        income_types=pc.INCOME_TYPE_LABELS,
        frequencies=pc.PAY_FREQUENCY_LABELS,
        pension_schemes=pc.PENSION_SCHEME_LABELS,
        student_loan_labels=uk_tax_tables.STUDENT_LOAN_LABELS,
        type_rules={
            'paye': sorted(pc.PAYE_TYPES | {'self_employed'}),
            'workplace_pension': sorted(pc.WORKPLACE_PENSION_TYPES),
            'student_loan': sorted(pc.PAYROLL_STUDENT_LOAN_TYPES | {'self_employed'}),
            'set_aside': sorted(pc.SET_ASIDE_TYPES | {'self_employed'}),
        },
    )


def _save_folding(recurring_id):
    from services.finance.expense_reimbursement_group_service import ExpenseReimbursementGroupService
    ExpenseReimbursementGroupService.set_folding_for_recurring_income(
        recurring_id, request.form.get('fold_expenses') == 'on'
    )


@income_bp.route('/income/recurring')
def recurring():
    """Income sources, grouped by person."""
    from services.finance.income_projection_service import IncomeProjectionService

    person = request.args.get('person') or None
    query = family_query(RecurringIncome)
    if person:
        query = query.filter_by(person=person)
    sources = query.order_by(RecurringIncome.is_active.desc(), RecurringIncome.person, RecurringIncome.source).all()
    snapshots = [IncomeProjectionService.source_snapshot(s) for s in sources]

    by_person = {}
    for snap in snapshots:
        label = MemberIdentityService.label(snap['source'].person, snap['source'].member_id)
        group = by_person.setdefault(label, {'snapshots': [], 'gross': Decimal('0'), 'monthly': Decimal('0')})
        group['snapshots'].append(snap)
        if snap['source'].is_active and not snap['ended']:
            group['gross'] += snap['terms'].gross_annual
            group['monthly'] += snap['monthly_take_home'] or Decimal('0')

    people = [p[0] for p in family_query(RecurringIncome).with_entities(RecurringIncome.person).distinct().order_by(RecurringIncome.person).all()]
    return render_template('income/recurring.html', by_person=by_person, people=people,
                           current_person=person, today=date.today(),
                           forecast_years=IncomeService.forecast_years(),
                           max_forecast_years=MAX_FORECAST_YEARS, **_labels())


def _labels():
    from services.finance import payroll_calculator as pc
    return dict(income_types=pc.INCOME_TYPE_LABELS, frequencies=pc.PAY_FREQUENCY_LABELS,
                pension_schemes=pc.PENSION_SCHEME_LABELS)


@income_bp.route('/income/recurring/add', methods=['GET', 'POST'])
def add_recurring():
    """Add an income source; forecasts are generated straight away."""
    if request.method == 'POST':
        try:
            recurring = IncomeService.save_income_source(request.form)
            _save_folding(recurring.id)
            flash('Income source added and forecasts generated.', 'success')
            return redirect(url_for('income.source', id=recurring.id))
        except Exception as e:
            _fail(e, 'Error adding income source.')
    return render_template('income/add_recurring.html', form=request.form, **_source_form_context())


@income_bp.route('/income/recurring/<int:id>')
def source(id):
    """One income source: current terms, timeline, payslips."""
    from models.income_change import IncomeChange
    from services.finance.expense_reimbursement_group_service import ExpenseReimbursementGroupService
    from services.finance.income_projection_service import IncomeProjectionService

    recurring = family_get_or_404(RecurringIncome, id)
    snapshot = IncomeProjectionService.source_snapshot(recurring)
    payslips = family_query(Income).filter(Income.recurring_income_id == recurring.id).order_by(Income.pay_date).all()
    today = date.today()
    return render_template(
        'income/source.html', src=recurring, snap=snapshot,
        history=[p for p in payslips if p.pay_date <= today][-12:][::-1],
        upcoming=[p for p in payslips if p.pay_date > today],
        change_types=IncomeChange.CHANGE_TYPE_LABELS,
        fixed_figures=IncomeService.uses_fixed_figures(recurring),
        fold_group=ExpenseReimbursementGroupService.get_folded_group_for_recurring_income(recurring.id),
        today=today, **_labels(),
    )


@income_bp.route('/income/recurring/<int:id>/edit', methods=['GET', 'POST'])
def edit_recurring(id):
    """Edit an income source; unsettled future forecasts are re-priced."""
    from services.finance.expense_reimbursement_group_service import ExpenseReimbursementGroupService

    recurring = family_get_or_404(RecurringIncome, id)
    if request.method == 'POST':
        try:
            IncomeService.save_income_source(request.form, recurring_id=id)
            _save_folding(id)
            flash('Income source saved — future forecasts updated.', 'success')
            return redirect(url_for('income.source', id=id))
        except Exception as e:
            _fail(e, 'Error saving income source.')
            recurring = family_get_or_404(RecurringIncome, id)
    fold_group = ExpenseReimbursementGroupService.get_folded_group_for_recurring_income(recurring.id)
    return render_template('income/edit_recurring.html', fold_group=fold_group,
                           form=request.form if request.method == 'POST' else None,
                           **_source_form_context(recurring))


@income_bp.route('/income/recurring/<int:id>/changes', methods=['POST'])
def add_change(id):
    """Add a pay rise / bonus / tax code / pension change to the timeline."""
    family_get_or_404(RecurringIncome, id)
    try:
        change = IncomeService.add_income_change(id, request.form)
        flash(f'{change.label} from {change.effective_date.strftime("%d %b %Y")} added — forecasts updated.', 'success')
    except Exception as e:
        _fail(e, 'Error adding change.')
    return redirect(url_for('income.source', id=id))


@income_bp.route('/income/changes/<int:change_id>/delete', methods=['POST'])
def delete_change(change_id):
    try:
        recurring_id = IncomeService.delete_income_change(change_id)
        flash('Change removed — forecasts updated.', 'success')
        return redirect(url_for('income.source', id=recurring_id))
    except Exception as e:
        _fail(e, 'Error removing change.')
    return redirect(url_for('income.recurring'))


@income_bp.route('/income/recurring/<int:id>/delete', methods=['POST'])
def delete_recurring(id):
    """Delete an income source; history is kept, forecasts removed."""
    try:
        IncomeService.delete_recurring_income(id)
        flash('Income source deleted. Paid history was kept; forecasts were removed.', 'success')
    except Exception as e:
        _fail(e, 'Error deleting income source.')
    return redirect(url_for('income.recurring'))


@income_bp.route('/income/refresh-forecasts', methods=['POST'])
def refresh_all():
    """Re-price every source's unsettled forecasts and fill the forecast horizon,
    optionally changing how many years ahead are kept first."""
    try:
        if request.form.get('forecast_years'):
            IncomeService.set_forecast_years(request.form['forecast_years'])
        result = IncomeService.refresh_all_forecasts()
        message = (f"Forecasts refreshed: {result['updated']} updated, {result['added']} added, "
                   f"{result['removed']} removed.")
        if result['failed']:
            message += f" {result['failed']} source(s) could not be refreshed — open them to check their settings."
        flash(message, 'warning' if result['failed'] else 'success')
    except Exception as e:
        _fail(e, 'Error refreshing forecasts.')
    return redirect(request.form.get('next') == 'sources' and url_for('income.recurring') or url_for('income.index'))


@income_bp.route('/income/plan')
def plan():
    """Long-range income plan per tax year, up to retirement."""
    from services.finance.income_projection_service import IncomeProjectionService

    try:
        result = IncomeProjectionService.build_plan(
            until_year=request.args.get('until') or None, person=request.args.get('person') or None)
    except ValueError as e:
        flash(str(e), 'danger')
        result = IncomeProjectionService.build_plan()
    people = [p[0] for p in family_query(RecurringIncome).with_entities(RecurringIncome.person).distinct().order_by(RecurringIncome.person).all()]
    retirement_people = []
    seen = set()
    for source in family_query(RecurringIncome).order_by(RecurringIncome.person, RecurringIncome.id).all():
        identity = (source.member_id, source.person if source.member_id is None else '')
        if identity in seen:
            continue
        seen.add(identity)
        retirement_people.append((
            MemberIdentityService.label(source.person, source.member_id), source.person, source.member_id,
            IncomeProjectionService.retirement_for(source.person, source.member_id),
            RetirementService.age_for(source.person, source.member_id),
        ))
    return render_template('income/plan.html', plan=result, people=people,
                           retirement_people=retirement_people,
                           current_person=request.args.get('person') or None, **_labels())


@income_bp.route('/income/plan/retirement', methods=['POST'])
def save_retirement():
    """Set a person's date of birth and retirement age (shared with the pension planner)."""
    from services.finance.income_projection_service import IncomeProjectionService

    person = request.form.get('person', '')
    try:
        info = IncomeProjectionService.set_retirement(person, request.form)
        if info:
            flash(f"{person} retires on {info['date'].strftime('%d %b %Y')} (age {info['age']}). "
                  'Regenerate pension projections to apply this change there.', 'success')
        else:
            flash(f'Retirement details cleared for {person}.', 'info')
    except Exception as e:
        _fail(e, 'Error saving retirement details.')
    return redirect(url_for('income.plan'))


@income_bp.route('/income/generate-missing', methods=['POST'])
def generate_missing():
    """Generate any missing forecast records up to the forecast horizon."""
    try:
        generated = IncomeService.generate_all_missing_income()
        if generated:
            flash(f'Checked {len(generated)} income record(s) up to the forecast horizon.', 'success')
        else:
            flash('All income records are up to date.', 'info')
    except Exception as e:
        _fail(e, 'Error generating income.')
    return redirect(url_for('income.index'))


@income_bp.route('/income/trim-forecasts', methods=['POST'])
def trim_forecasts():
    """Delete surplus far-future forecast records and reset last_generated_date."""
    try:
        try:
            months = int(request.form.get('months_ahead', 24))
        except (TypeError, ValueError):
            raise ValueError('Months ahead must be a whole number.')
        result = IncomeService.trim_future_forecasts(months_ahead=months)
        if result['deleted']:
            flash(
                f"Trimmed {result['deleted']} future forecast record(s) "
                f"(+{result['transactions']} transaction(s)) beyond {months} months.",
                'success'
            )
        else:
            flash('No surplus forecast records found beyond that horizon.', 'info')
    except Exception as e:
        _fail(e, 'Error trimming forecasts.')

    return redirect(url_for('income.index'))


@income_bp.route('/income/recurring/<int:id>/regenerate', methods=['POST'])
def regenerate_range(id):
    """Regenerate income records for a date range"""
    recurring = family_get_or_404(RecurringIncome, id)
    try:
        start_date = _parse_form_date('start_date', 'Start date')
        end_date = _parse_form_date('end_date', 'End date')
        result = IncomeService.regenerate_income_range(
            recurring.id, start_date, end_date, force=request.form.get('force') == 'on',
        )
        messages = []
        if result['deleted'] > 0:
            messages.append(f"deleted {result['deleted']} record(s)")
        if result['regenerated'] > 0:
            messages.append(f"regenerated {result['regenerated']} record(s)")
        if result['skipped'] > 0:
            messages.append(f"skipped {result['skipped']} paid / actual record(s)")
        if messages:
            flash(f"Done: {', '.join(messages)}.", 'success')
        else:
            flash('No records were affected.', 'info')
    except Exception as e:
        _fail(e, 'Error regenerating income.')
    return redirect(url_for('income.source', id=id))


@income_bp.route('/income/recurring/<int:id>/end-job', methods=['POST'])
def end_job(id):
    """Leave a job / retire: close the source and delete future unpaid records."""
    recurring = family_get_or_404(RecurringIncome, id)
    try:
        last_pay_date = _parse_form_date('last_pay_date', 'Last pay date')
        result = IncomeService.end_job(recurring.id, last_pay_date)
        msg = f"Income ended on {last_pay_date.strftime('%d/%m/%Y')}. "
        if result['deleted']:
            msg += f"Removed {result['deleted']} future forecast(s) and their transactions. "
        if result['kept_paid']:
            msg += f"{result['kept_paid']} paid record(s) were kept."
        flash(msg.strip(), 'success')
    except Exception as e:
        _fail(e, 'Error ending income.')
    return redirect(url_for('income.source', id=id))


@income_bp.route('/income/reperiod-transactions', methods=['POST'])
def reperiod_transactions():
    """Re-stamp payday_period on all transactions, optionally updating the payday_day setting first."""
    from services.finance.payday_service import PaydayService

    if not current_user.is_household_owner:
        abort(403)

    try:
        _, new_day = PaydayService.change_payday_and_reperiod(request.form)
        # The count includes other members' private transactions, so don't show it.
        flash(
            "Payday periods recalculated."
            + (f" Payday day is now the {new_day}." if new_day else ""),
            'success'
        )

    except Exception as e:
        _fail(e, 'Error updating payday periods.')

    return redirect(url_for('income.recurring'))
