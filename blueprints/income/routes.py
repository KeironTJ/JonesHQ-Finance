from flask import render_template, request, redirect, url_for, flash, jsonify
from . import income_bp
from models.income import Income
from models.recurring_income import RecurringIncome
from models.accounts import Account
from models.categories import Category
from services.income_service import IncomeService
from extensions import db
from datetime import datetime
from decimal import Decimal


@income_bp.route('/income')
def index():
    """List all income records"""
    # Get filter parameters
    person = request.args.get('person', None)
    year = request.args.get('year', None)
    
    # Get summary
    summary = IncomeService.get_income_summary(person=person, year=year)
    
    # Get all accounts for the dropdown
    accounts = Account.query.filter_by(is_active=True).order_by(Account.name).all()
    
    # Get unique people and years for filters
    people = db.session.query(Income.person).distinct().order_by(Income.person).all()
    people = [p[0] for p in people] if people else ['Keiron']
    
    years = db.session.query(db.func.substr(Income.tax_year, 1, 4).label('year')).distinct().all()
    years = sorted([y[0] for y in years], reverse=True) if years else []
    
    return render_template('income/index.html',
                         income_records=summary['records'],
                         summary=summary,
                         accounts=accounts,
                         people=people,
                         years=years,
                         current_person=person,
                         current_year=year)


@income_bp.route('/income/add', methods=['GET', 'POST'])
def add():
    """Add a new income record"""
    if request.method == 'POST':
        try:
            # Parse form data
            person = request.form.get('person', 'Keiron')
            pay_date = datetime.strptime(request.form['pay_date'], '%Y-%m-%d').date()
            gross_annual = Decimal(request.form['gross_annual'])
            employer_pension_pct = Decimal(request.form.get('employer_pension_pct', 0))
            employee_pension_pct = Decimal(request.form.get('employee_pension_pct', 0))
            tax_code = request.form['tax_code']
            avc = Decimal(request.form.get('avc', 0))
            other = Decimal(request.form.get('other', 0))
            deposit_account_id = request.form.get('deposit_account_id')
            source = request.form.get('source', '')
            create_transaction = request.form.get('create_transaction') == 'on'
            
            # Convert empty account_id to None
            if deposit_account_id:
                deposit_account_id = int(deposit_account_id)
            else:
                deposit_account_id = None
            
            # Create income record
            income = IncomeService.create_income_record(
                person=person,
                pay_date=pay_date,
                gross_annual=gross_annual,
                employer_pension_pct=employer_pension_pct,
                employee_pension_pct=employee_pension_pct,
                tax_code=tax_code,
                avc=avc,
                other=other,
                deposit_account_id=deposit_account_id,
                source=source,
                create_transaction=create_transaction
            )
            
            flash(f'Income record added successfully! Take home: £{income.take_home:,.2f}', 'success')
            return redirect(url_for('income.index'))
            
        except Exception as e:
            flash(f'Error adding income: {str(e)}', 'danger')
            return redirect(url_for('income.add'))
    
    # GET request - show form
    accounts = Account.query.filter_by(is_active=True).order_by(Account.name).all()
    return render_template('income/add.html', accounts=accounts)


@income_bp.route('/income/<int:id>/edit', methods=['GET', 'POST'])
def edit(id):
    """Edit an income record"""
    income = Income.query.get_or_404(id)
    
    if request.method == 'POST':
        try:
            # Update basic fields
            income.person = request.form.get('person', income.person)
            income.pay_date = datetime.strptime(request.form['pay_date'], '%Y-%m-%d').date()
            income.gross_annual_income = Decimal(request.form['gross_annual'])
            income.employer_pension_percent = Decimal(request.form.get('employer_pension_pct', 0))
            income.employee_pension_percent = Decimal(request.form.get('employee_pension_pct', 0))
            income.tax_code = request.form['tax_code']
            income.avc = Decimal(request.form.get('avc', 0))
            income.other_deductions = Decimal(request.form.get('other', 0))
            income.source = request.form.get('source', '')
            
            # Update account
            deposit_account_id = request.form.get('deposit_account_id')
            if deposit_account_id:
                income.deposit_account_id = int(deposit_account_id)
            else:
                income.deposit_account_id = None
            
            # Recalculate all derived fields
            result = IncomeService.calculate_tax_and_ni(
                gross_annual=income.gross_annual_income,
                tax_code=income.tax_code,
                pension_amount=(income.employer_pension_percent + income.employee_pension_percent) * income.gross_annual_income / 100
            )
            
            # Update calculated fields
            income.gross_monthly_income = income.gross_annual_income / 12
            income.employer_pension_amount = income.gross_monthly_income * income.employer_pension_percent / 100
            income.employee_pension_amount = income.gross_monthly_income * income.employee_pension_percent / 100
            income.total_pension = income.employer_pension_amount + income.employee_pension_amount
            income.income_tax = result['tax'] / 12
            income.national_insurance = result['ni'] / 12
            income.take_home = income.gross_monthly_income - income.income_tax - income.national_insurance - income.employee_pension_amount - income.avc - income.other_deductions
            
            # Sync changes to linked transaction
            IncomeService.sync_income_to_transaction(income)
            
            db.session.commit()
            
            flash('Income record updated successfully!', 'success')
            return redirect(url_for('income.index'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating income: {str(e)}', 'danger')
    
    # GET request - show form
    accounts = Account.query.filter_by(is_active=True).order_by(Account.name).all()
    return render_template('income/edit.html', income=income, accounts=accounts)


@income_bp.route('/income/<int:id>/delete', methods=['POST'])
def delete(id):
    """Delete an income record"""
    income = Income.query.get_or_404(id)
    
    try:
        from models.transactions import Transaction
        
        # Break circular reference first
        if income.transaction_id:
            transaction = Transaction.query.get(income.transaction_id)
            if transaction:
                # Clear both sides of the relationship
                transaction.income_id = None
                income.transaction_id = None
                db.session.flush()
                # Now delete the transaction
                db.session.delete(transaction)
        
        db.session.delete(income)
        db.session.commit()
        flash('Income record deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting income: {str(e)}', 'danger')
    
    return redirect(url_for('income.index'))


@income_bp.route('/income/delete-multiple', methods=['POST'])
def delete_multiple():
    """Delete multiple income records"""
    income_ids = request.form.getlist('income_ids')
    
    if not income_ids:
        flash('No income records selected.', 'warning')
        return redirect(url_for('income.index'))
    
    try:
        deleted_count = 0
        from models.transactions import Transaction
        
        for income_id in income_ids:
            income = Income.query.get(income_id)
            if income:
                # Break circular reference first
                if income.transaction_id:
                    transaction = Transaction.query.get(income.transaction_id)
                    if transaction:
                        # Clear both sides of the relationship
                        transaction.income_id = None
                        income.transaction_id = None
                        db.session.flush()
                        # Now delete the transaction
                        db.session.delete(transaction)
                
                db.session.delete(income)
                deleted_count += 1
        
        db.session.commit()
        flash(f'Successfully deleted {deleted_count} income record(s) and their linked transactions.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting income records: {str(e)}', 'danger')
    
    return redirect(url_for('income.index'))


@income_bp.route('/income/toggle/<int:id>/paid', methods=['POST'])
def toggle_paid(id):
    """Toggle the is_paid flag for an income record"""
    income = Income.query.get_or_404(id)
    
    try:
        # Toggle the paid status
        income.is_paid = not income.is_paid
        
        # Sync with linked transaction if it exists
        if income.transaction_id:
            from models.transactions import Transaction
            transaction = Transaction.query.get(income.transaction_id)
            if transaction:
                transaction.is_paid = income.is_paid
        
        db.session.commit()
        
        return jsonify({
            'id': income.id,
            'field': 'paid',
            'value': income.is_paid
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@income_bp.route('/income/calculate-preview', methods=['POST'])
def calculate_preview():
    """AJAX endpoint to preview tax/NI calculations"""
    try:
        data = request.get_json()
        gross_annual = Decimal(data['gross_annual'])
        employer_pension_pct = Decimal(data.get('employer_pension_pct', 0))
        employee_pension_pct = Decimal(data.get('employee_pension_pct', 0))
        tax_code = data['tax_code']
        avc = Decimal(data.get('avc', 0))
        other = Decimal(data.get('other', 0))
        
        # Calculate pension amount
        pension_amount = (employer_pension_pct + employee_pension_pct) * gross_annual / 100
        
        # Calculate tax and NI
        result = IncomeService.calculate_tax_and_ni(
            gross_annual=gross_annual,
            tax_code=tax_code,
            pension_amount=pension_amount
        )
        
        # Calculate monthly breakdown
        gross_monthly = gross_annual / 12
        employer_pension = gross_monthly * employer_pension_pct / 100
        employee_pension = gross_monthly * employee_pension_pct / 100
        total_pension = employer_pension + employee_pension
        monthly_tax = result['tax'] / 12
        monthly_ni = result['ni'] / 12
        take_home = gross_monthly - monthly_tax - monthly_ni - employee_pension - avc - other
        
        return jsonify({
            'success': True,
            'gross_monthly': float(gross_monthly),
            'employer_pension': float(employer_pension),
            'employee_pension': float(employee_pension),
            'total_pension': float(total_pension),
            'income_tax': float(monthly_tax),
            'national_insurance': float(monthly_ni),
            'take_home': float(take_home),
            'annual_tax': float(result['tax']),
            'annual_ni': float(result['ni'])
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


# ============= RECURRING INCOME ROUTES =============

@income_bp.route('/income/recurring')
def recurring():
    """List all recurring income templates"""
    person = request.args.get('person', None)
    
    query = RecurringIncome.query
    if person:
        query = query.filter_by(person=person)
    
    recurring_incomes = query.order_by(RecurringIncome.person, RecurringIncome.source).all()
    
    # Get unique people for filter
    people = db.session.query(RecurringIncome.person).distinct().order_by(RecurringIncome.person).all()
    people = [p[0] for p in people] if people else ['Keiron']
    
    accounts = Account.query.filter_by(is_active=True).order_by(Account.name).all()
    
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
            recurring = RecurringIncome(
                person=request.form.get('person', 'Keiron'),
                start_date=datetime.strptime(request.form['start_date'], '%Y-%m-%d').date(),
                end_date=datetime.strptime(request.form['end_date'], '%Y-%m-%d').date() if request.form.get('end_date') else None,
                pay_day=int(request.form['pay_day']),
                gross_annual_income=Decimal(request.form['gross_annual']),
                employer_pension_percent=Decimal(request.form.get('employer_pension_pct', 0)),
                employee_pension_percent=Decimal(request.form.get('employee_pension_pct', 0)),
                tax_code=request.form['tax_code'],
                avc=Decimal(request.form.get('avc', 0)),
                other_deductions=Decimal(request.form.get('other', 0)),
                deposit_account_id=int(request.form['deposit_account_id']) if request.form.get('deposit_account_id') else None,
                category_id=int(request.form['category_id']) if request.form.get('category_id') else None,
                auto_create_transaction=request.form.get('auto_create_transaction') == 'on',
                source=request.form.get('source', ''),
                description=request.form.get('description', ''),
                is_active=True,
                # Manual override fields
                use_manual_deductions=request.form.get('use_manual_deductions') == 'on',
                manual_tax_monthly=Decimal(request.form.get('manual_tax_monthly', 0)) if request.form.get('manual_tax_monthly') else None,
                manual_ni_monthly=Decimal(request.form.get('manual_ni_monthly', 0)) if request.form.get('manual_ni_monthly') else None,
                manual_employee_pension=Decimal(request.form.get('manual_employee_pension', 0)) if request.form.get('manual_employee_pension') else None,
                manual_employer_pension=Decimal(request.form.get('manual_employer_pension', 0)) if request.form.get('manual_employer_pension') else None,
                manual_take_home=Decimal(request.form.get('manual_take_home', 0)) if request.form.get('manual_take_home') else None
            )
            
            db.session.add(recurring)
            db.session.commit()
            
            # Generate missing income records
            generated = IncomeService.generate_missing_income(recurring.id)
            
            flash(f'Recurring income added successfully! Generated {len(generated)} income record(s).', 'success')
            return redirect(url_for('income.recurring'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error adding recurring income: {str(e)}', 'danger')
    
    accounts = Account.query.filter_by(is_active=True).order_by(Account.name).all()
    categories = Category.query.filter_by(category_type='income').order_by(Category.head_budget, Category.sub_budget).all()
    return render_template('income/add_recurring.html', accounts=accounts, categories=categories)


@income_bp.route('/income/recurring/<int:id>/edit', methods=['GET', 'POST'])
def edit_recurring(id):
    """Edit a recurring income template"""
    recurring = RecurringIncome.query.get_or_404(id)
    
    if request.method == 'POST':
        try:
            recurring.person = request.form.get('person', recurring.person)
            recurring.start_date = datetime.strptime(request.form['start_date'], '%Y-%m-%d').date()
            recurring.end_date = datetime.strptime(request.form['end_date'], '%Y-%m-%d').date() if request.form.get('end_date') else None
            recurring.pay_day = int(request.form['pay_day'])
            recurring.gross_annual_income = Decimal(request.form['gross_annual'])
            recurring.employer_pension_percent = Decimal(request.form.get('employer_pension_pct', 0))
            recurring.employee_pension_percent = Decimal(request.form.get('employee_pension_pct', 0))
            recurring.tax_code = request.form['tax_code']
            recurring.avc = Decimal(request.form.get('avc', 0))
            recurring.other_deductions = Decimal(request.form.get('other', 0))
            recurring.deposit_account_id = int(request.form['deposit_account_id']) if request.form.get('deposit_account_id') else None
            recurring.category_id = int(request.form['category_id']) if request.form.get('category_id') else None
            recurring.auto_create_transaction = request.form.get('auto_create_transaction') == 'on'
            recurring.source = request.form.get('source', '')
            recurring.description = request.form.get('description', '')
            recurring.is_active = request.form.get('is_active') == 'on'
            
            # Manual override fields
            recurring.use_manual_deductions = request.form.get('use_manual_deductions') == 'on'
            if recurring.use_manual_deductions:
                recurring.manual_tax_monthly = Decimal(request.form.get('manual_tax_monthly', 0)) if request.form.get('manual_tax_monthly') else None
                recurring.manual_ni_monthly = Decimal(request.form.get('manual_ni_monthly', 0)) if request.form.get('manual_ni_monthly') else None
                recurring.manual_employee_pension = Decimal(request.form.get('manual_employee_pension', 0)) if request.form.get('manual_employee_pension') else None
                recurring.manual_employer_pension = Decimal(request.form.get('manual_employer_pension', 0)) if request.form.get('manual_employer_pension') else None
                recurring.manual_take_home = Decimal(request.form.get('manual_take_home', 0)) if request.form.get('manual_take_home') else None
            else:
                # Clear manual values if not using manual mode
                recurring.manual_tax_monthly = None
                recurring.manual_ni_monthly = None
                recurring.manual_employee_pension = None
                recurring.manual_employer_pension = None
                recurring.manual_take_home = None
            
            db.session.commit()
            flash('Recurring income updated successfully!', 'success')
            return redirect(url_for('income.recurring'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating recurring income: {str(e)}', 'danger')
    
    accounts = Account.query.filter_by(is_active=True).order_by(Account.name).all()
    categories = Category.query.filter_by(category_type='income').order_by(Category.head_budget, Category.sub_budget).all()
    return render_template('income/edit_recurring.html', recurring=recurring, accounts=accounts, categories=categories)


@income_bp.route('/income/recurring/<int:id>/delete', methods=['POST'])
def delete_recurring(id):
    """Delete a recurring income template"""
    recurring = RecurringIncome.query.get_or_404(id)
    
    try:
        db.session.delete(recurring)
        db.session.commit()
        flash('Recurring income deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting recurring income: {str(e)}', 'danger')
    
    return redirect(url_for('income.recurring'))


@income_bp.route('/income/generate-missing', methods=['POST'])
def generate_missing():
    """Generate all missing income records from recurring templates"""
    try:
        generated = IncomeService.generate_all_missing_income()
        
        if generated:
            flash(f'Successfully generated {len(generated)} income record(s)!', 'success')
        else:
            flash('All income records are up to date.', 'info')
            
    except Exception as e:
        flash(f'Error generating income: {str(e)}', 'danger')
    
    return redirect(url_for('income.index'))


@income_bp.route('/income/recurring/<int:id>/regenerate', methods=['POST'])
def regenerate_range(id):
    """Regenerate income records for a date range"""
    recurring = RecurringIncome.query.get_or_404(id)
    
    try:
        start_date = datetime.strptime(request.form['start_date'], '%Y-%m-%d').date()
        end_date = datetime.strptime(request.form['end_date'], '%Y-%m-%d').date()
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
        db.session.rollback()
        flash(f'Error regenerating income: {str(e)}', 'danger')
    
    return redirect(url_for('income.edit_recurring', id=id))
