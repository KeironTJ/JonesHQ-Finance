from flask import render_template, request, redirect, url_for, flash, jsonify
from . import income_bp
from models.income import Income
from models.accounts import Account
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
        # If there's a linked transaction, optionally delete it
        if income.transaction_id:
            from models.transactions import Transaction
            transaction = Transaction.query.get(income.transaction_id)
            if transaction:
                db.session.delete(transaction)
        
        db.session.delete(income)
        db.session.commit()
        flash('Income record deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting income: {str(e)}', 'danger')
    
    return redirect(url_for('income.index'))


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
