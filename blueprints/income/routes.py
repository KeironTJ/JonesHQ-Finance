from flask import current_app, render_template, request, redirect, url_for, flash, jsonify
from sqlalchemy import func
from . import income_bp
from models.income import Income
from models.recurring_income import RecurringIncome
from models.accounts import Account
from models.categories import Category
from models.users import User
from services.finance.income_service import IncomeService
from extensions import db
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
from utils.db_helpers import family_query, family_get_or_404


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
    return people or ['Household']


@income_bp.route('/income')
def index():
    """List all income records — auto-generates missing records on load."""
    # Silently auto-generate up to 13 months ahead
    try:
        end = (date.today().replace(day=1) + relativedelta(months=13))
        IncomeService.generate_all_missing_income(end_date=end)
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
                           today_year=datetime.now().year,
                           linked_expenses_by_income=linked_expenses_by_income,
                           folded_recurring_income_ids=folded_recurring_income_ids)


@income_bp.route('/income/add', methods=['GET', 'POST'])
def add():
    """Add a new one-off income record"""
    if request.method == 'POST':
        try:
            income = IncomeService.create_one_off_income(request.form)
            flash(f'Income record added successfully! Take home: ?{income.take_home:,.2f}', 'success')
            return redirect(url_for('income.index'))
        except Exception as e:
            _fail(e, 'Error adding income.')
            return redirect(url_for('income.add'))

    accounts = family_query(Account).filter_by(is_active=True).order_by(Account.name).all()
    return render_template('income/add.html', accounts=accounts, people=_get_income_people())


@income_bp.route('/income/<int:id>/edit', methods=['GET', 'POST'])
def edit(id):
    """Edit an income record ? supports both calculated and manual-override modes."""
    income = family_get_or_404(Income, id)

    if request.method == 'POST':
        try:
            income = IncomeService.update_income_record(id, request.form)
            flash(f'Income record updated ? take home: ?{income.take_home:,.2f}', 'success')
            return redirect(url_for('income.index'))
        except Exception as e:
            _fail(e, 'Error updating income.')
            income = family_get_or_404(Income, id)

    accounts = family_query(Account).filter_by(is_active=True).order_by(Account.name).all()
    return render_template('income/edit.html', income=income, accounts=accounts, people=_get_income_people())


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
        flash(f'Actual payslip for {income.pay_date.strftime("%B %Y")} recorded ? transaction updated.', 'success')
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


# ============= RECURRING INCOME ROUTES =============

@income_bp.route('/income/recurring')
def recurring():
    """List all recurring income templates"""
    person = request.args.get('person', None)
    
    query = family_query(RecurringIncome)
    if person:
        query = query.filter_by(person=person)
    
    recurring_incomes = query.order_by(RecurringIncome.person, RecurringIncome.source).all()
    
    # Get unique people for filter
    people = family_query(RecurringIncome).with_entities(RecurringIncome.person).distinct().order_by(RecurringIncome.person).all()
    people = [p[0] for p in people] if people else _get_income_people()
    
    accounts = family_query(Account).filter_by(is_active=True).order_by(Account.name).all()
    
    return render_template('income/recurring.html',
                         recurring_incomes=recurring_incomes,
                         people=people,
                         accounts=accounts,
                         current_person=person)


@income_bp.route('/income/recurring/add', methods=['GET', 'POST'])
def add_recurring():
    """Add a new recurring income template"""
    if request.method == 'POST':
        try:
            recurring = IncomeService.create_recurring_income(request.form)
            
            # Generate missing income records
            generated = IncomeService.generate_missing_income(recurring.id)
            
            flash(f'Recurring income added successfully! Generated {len(generated)} income record(s).', 'success')
            return redirect(url_for('income.recurring'))
            
        except Exception as e:
            _fail(e, 'Error adding recurring income.')
    
    accounts = family_query(Account).filter_by(is_active=True).order_by(Account.name).all()
    categories = _income_categories()
    return render_template('income/add_recurring.html', accounts=accounts, categories=categories, people=_get_income_people())


@income_bp.route('/income/recurring/<int:id>/edit', methods=['GET', 'POST'])
def edit_recurring(id):
    """Edit a recurring income template"""
    recurring = family_get_or_404(RecurringIncome, id)
    
    if request.method == 'POST':
        try:
            recurring = IncomeService.update_recurring_income(id, request.form)
            from services.finance.expense_reimbursement_group_service import ExpenseReimbursementGroupService
            ExpenseReimbursementGroupService.set_folding_for_recurring_income(
                recurring.id, request.form.get('fold_expenses') == 'on'
            )
            flash('Recurring income updated successfully!', 'success')
            return redirect(url_for('income.recurring'))
            
        except Exception as e:
            _fail(e, 'Error updating recurring income.')
            recurring = family_get_or_404(RecurringIncome, id)
    
    accounts = family_query(Account).filter_by(is_active=True).order_by(Account.name).all()
    categories = _income_categories()
    from services.finance.expense_reimbursement_group_service import ExpenseReimbursementGroupService
    fold_group = ExpenseReimbursementGroupService.get_folded_group_for_recurring_income(recurring.id)
    return render_template('income/edit_recurring.html', recurring=recurring, accounts=accounts, categories=categories, people=_get_income_people(), fold_group=fold_group)


@income_bp.route('/income/recurring/<int:id>/delete', methods=['POST'])
def delete_recurring(id):
    """Delete a recurring income template"""
    try:
        IncomeService.delete_recurring_income(id)
        flash('Recurring income deleted successfully!', 'success')
    except Exception as e:
        _fail(e, 'Error deleting recurring income.')
    
    return redirect(url_for('income.recurring'))


@income_bp.route('/income/generate-missing', methods=['POST'])
def generate_missing():
    """Generate all missing income records from recurring templates (13-month window)."""
    try:
        end = date.today().replace(day=1) + relativedelta(months=13)
        generated = IncomeService.generate_all_missing_income(end_date=end)
        if generated:
            flash(f'Generated {len(generated)} income record(s).', 'success')
        else:
            flash('All income records are up to date.', 'info')
    except Exception as e:
        _fail(e, 'Error generating income.')
    return redirect(url_for('income.index'))


@income_bp.route('/income/generate-full-range', methods=['POST'])
def generate_full_range():
    """Generate the complete retirement-horizon range for all active templates (no end_date cap)."""
    try:
        generated = IncomeService.generate_all_missing_income()  # uses template end_date or 20-year default
        if generated:
            flash(f'Full range generated: {len(generated)} income record(s) added.', 'success')
        else:
            flash('All income records are already up to date across the full range.', 'info')
    except Exception as e:
        _fail(e, 'Error generating full range.')
    return redirect(url_for('income.index'))


@income_bp.route('/income/trim-forecasts', methods=['POST'])
def trim_forecasts():
    """Delete surplus far-future forecast records and reset last_generated_date."""
    try:
        try:
            months = int(request.form.get('months_ahead', 13))
        except (TypeError, ValueError):
            raise ValueError('Months ahead must be a whole number.')
        result = IncomeService.trim_future_forecasts(months_ahead=months)
        if result['deleted']:
            flash(
                f"Trimmed {result['deleted']} future forecast record(s) "
                f"(+{result['transactions']} transaction(s)) beyond {months} months. "
                f"Templates reset — auto-generate will fill forward from the next page load.",
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
        force = request.form.get('force') == 'on'
        
        result = IncomeService.regenerate_income_range(
            recurring.id,
            start_date,
            end_date,
            force=force
        )
        
        # Build result message
        messages = []
        if result['deleted'] > 0:
            messages.append(f"Deleted {result['deleted']} record(s)")
        if result['regenerated'] > 0:
            messages.append(f"regenerated {result['regenerated']} record(s)")
        if result['skipped'] > 0:
            messages.append(f"skipped {result['skipped']} record(s) with transactions")
        
        if messages:
            flash(f"Successfully {', '.join(messages)}!", 'success')
        else:
            flash('No records were affected.', 'info')
            
    except Exception as e:
        _fail(e, 'Error regenerating income.')
    
    return redirect(url_for('income.edit_recurring', id=id))


@income_bp.route('/income/recurring/<int:id>/end-job', methods=['POST'])
def end_job(id):
    """End a recurring income job: close the template and delete future unpaid records."""
    recurring = family_get_or_404(RecurringIncome, id)

    try:
        last_pay_date = _parse_form_date('last_pay_date', 'Last pay date')
        result = IncomeService.end_job(recurring.id, last_pay_date)

        msg = f"Job ended on {last_pay_date.strftime('%d/%m/%Y')}. "
        if result['deleted']:
            msg += f"Deleted {result['deleted']} future unpaid income record(s) and their transactions. "
        if result['kept_paid']:
            msg += f"{result['kept_paid']} already-paid record(s) were kept."
        flash(msg.strip(), 'success')

    except Exception as e:
        _fail(e, 'Error ending job.')

    return redirect(url_for('income.recurring'))


@income_bp.route('/income/reperiod-transactions', methods=['POST'])
def reperiod_transactions():
    """Re-stamp payday_period on all transactions, optionally updating the payday_day setting first."""
    from services.finance.payday_service import PaydayService
    from models.settings import Settings

    try:
        new_payday_day = request.form.get('new_payday_day', '').strip()
        if new_payday_day:
            day = int(new_payday_day)
            if not 0 <= day <= 31:
                raise ValueError("Payday day must be between 1 and 31 (or 0 for last day of month).")
            Settings.set_value('payday_day', day, description='Day of month salary is paid', setting_type='int')
            db.session.commit()

        updated = PaydayService.reperiod_all_transactions()
        flash(
            f"Payday periods updated for {updated} transaction(s)."
            + (f" Payday day is now the {new_payday_day}." if new_payday_day else ""),
            'success'
        )

    except Exception as e:
        _fail(e, 'Error updating payday periods.')

    return redirect(url_for('income.recurring'))

