from flask import render_template, request, redirect, url_for, flash
from . import pensions_bp
from models.pensions import Pension
from models.pension_snapshots import PensionSnapshot
from extensions import db
from datetime import datetime
from decimal import Decimal


@pensions_bp.route('/pensions')
def index():
    """List all pensions"""
    # Get filter parameter
    person = request.args.get('person', None)
    
    query = Pension.query
    if person:
        query = query.filter_by(person=person)
    
    pensions = query.order_by(Pension.person, Pension.provider).all()
    
    # Get unique people for filter
    people = db.session.query(Pension.person).distinct().order_by(Pension.person).all()
    people = [p[0] for p in people] if people else ['Keiron']
    
    # Calculate totals
    total_value = sum([p.current_value for p in pensions if p.is_active])
    active_count = len([p for p in pensions if p.is_active])
    
    return render_template('pensions/index.html', 
                         pensions=pensions,
                         people=people,
                         current_person=person,
                         total_value=total_value,
                         active_count=active_count)


@pensions_bp.route('/pensions/add', methods=['GET', 'POST'])
def add():
    """Add a new pension"""
    if request.method == 'POST':
        try:
            pension = Pension(
                person=request.form.get('person', 'Keiron'),
                provider=request.form['provider'],
                account_number=request.form.get('account_number', ''),
                current_value=Decimal(request.form.get('current_value', 0)),
                contribution_rate=Decimal(request.form.get('contribution_rate', 0)),
                employer_contribution=Decimal(request.form.get('employer_contribution', 0)),
                is_active=request.form.get('is_active') == 'on'
            )
            
            db.session.add(pension)
            db.session.commit()
            
            flash(f'Pension added successfully: {pension.provider}', 'success')
            return redirect(url_for('pensions.index'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error adding pension: {str(e)}', 'danger')
    
    return render_template('pensions/add.html')


@pensions_bp.route('/pensions/<int:id>/edit', methods=['GET', 'POST'])
def edit(id):
    """Edit a pension"""
    pension = Pension.query.get_or_404(id)
    
    if request.method == 'POST':
        try:
            pension.person = request.form.get('person', pension.person)
            pension.provider = request.form['provider']
            pension.account_number = request.form.get('account_number', '')
            pension.current_value = Decimal(request.form.get('current_value', 0))
            pension.contribution_rate = Decimal(request.form.get('contribution_rate', 0))
            pension.employer_contribution = Decimal(request.form.get('employer_contribution', 0))
            pension.is_active = request.form.get('is_active') == 'on'
            
            db.session.commit()
            flash('Pension updated successfully!', 'success')
            return redirect(url_for('pensions.index'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating pension: {str(e)}', 'danger')
    
    return render_template('pensions/edit.html', pension=pension)


@pensions_bp.route('/pensions/<int:id>/delete', methods=['POST'])
def delete(id):
    """Delete a pension"""
    pension = Pension.query.get_or_404(id)
    
    try:
        db.session.delete(pension)
        db.session.commit()
        flash('Pension deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting pension: {str(e)}', 'danger')
    
    return redirect(url_for('pensions.index'))


@pensions_bp.route('/pensions/<int:id>/snapshots')
def snapshots(id):
    """View snapshots for a pension"""
    pension = Pension.query.get_or_404(id)
    snapshots = PensionSnapshot.query.filter_by(pension_id=id).order_by(PensionSnapshot.review_date.desc()).all()
    
    return render_template('pensions/snapshots.html', pension=pension, snapshots=snapshots)


@pensions_bp.route('/pensions/<int:id>/snapshots/add', methods=['GET', 'POST'])
def add_snapshot(id):
    """Add a snapshot for a pension"""
    pension = Pension.query.get_or_404(id)
    
    if request.method == 'POST':
        try:
            review_date = datetime.strptime(request.form['review_date'], '%Y-%m-%d').date()
            value = Decimal(request.form['value'])
            
            # Get previous snapshot
            previous = PensionSnapshot.query.filter_by(pension_id=id)\
                .filter(PensionSnapshot.review_date < review_date)\
                .order_by(PensionSnapshot.review_date.desc())\
                .first()
            
            # Calculate growth
            growth_percent = None
            if previous and previous.value > 0:
                growth_percent = ((value - previous.value) / previous.value) * 100
            
            # Create snapshot
            snapshot = PensionSnapshot(
                pension_id=id,
                review_date=review_date,
                value=value,
                growth_percent=growth_percent
            )
            
            db.session.add(snapshot)
            
            # Update pension current value
            pension.current_value = value
            
            db.session.commit()
            
            flash(f'Snapshot added successfully! Value: £{value:,.2f}' + 
                  (f', Growth: {growth_percent:.2f}%' if growth_percent else ''), 'success')
            return redirect(url_for('pensions.snapshots', id=id))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error adding snapshot: {str(e)}', 'danger')
    
    return render_template('pensions/add_snapshot.html', pension=pension)
