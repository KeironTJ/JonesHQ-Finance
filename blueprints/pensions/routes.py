from flask import render_template, request, redirect, url_for, flash, jsonify
from . import pensions_bp
from models.pensions import Pension
from models.pension_snapshots import PensionSnapshot
from models.settings import Settings
from services.pension_service import PensionService
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
                is_active=request.form.get('is_active') == 'on',
                retirement_age=int(request.form.get('retirement_age', 65)),
                monthly_contribution=Decimal(request.form.get('monthly_contribution', 0))
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
            pension.retirement_age = int(request.form.get('retirement_age', 65))
            pension.monthly_contribution = Decimal(request.form.get('monthly_contribution', 0))
            
            db.session.commit()
            
            # Regenerate projections if auto-enabled
            if Settings.get_value('auto_regenerate_projections', True):
                PensionService.save_projections(pension, scenario='default')
            
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
    # Order by review_date ascending (oldest first), then by is_projection (actual before projected)
    snapshots = PensionSnapshot.query.filter_by(pension_id=id).order_by(
        PensionSnapshot.review_date.asc(),
        PensionSnapshot.is_projection.asc()
    ).all()
    
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
            
            # Remove any existing projection for this exact date (now superseded by actual)
            PensionSnapshot.query.filter_by(
                pension_id=id,
                review_date=review_date,
                is_projection=True
            ).delete()
            
            db.session.add(snapshot)
            
            # Update pension current value
            pension.current_value = value
            
            db.session.commit()
            
            # Auto-regenerate projections if enabled
            if Settings.get_value('auto_regenerate_projections', True):
                PensionService.save_projections(pension, scenario='default')
            
            flash(f'Snapshot added successfully! Value: £{value:,.2f}' + 
                  (f', Growth: {growth_percent:.2f}%' if growth_percent else ''), 'success')
            return redirect(url_for('pensions.snapshots', id=id))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error adding snapshot: {str(e)}', 'danger')
    
    return render_template('pensions/add_snapshot.html', pension=pension)


@pensions_bp.route('/pensions/<int:pension_id>/snapshot/<int:snapshot_id>/confirm', methods=['POST'])
def confirm_snapshot(pension_id, snapshot_id):
    """Convert a projection to an actual snapshot (firm it up)"""
    pension = Pension.query.get_or_404(pension_id)
    snapshot = PensionSnapshot.query.get_or_404(snapshot_id)
    
    if snapshot.pension_id != pension_id:
        flash('Invalid snapshot for this pension.', 'danger')
        return redirect(url_for('pensions.snapshots', id=pension_id))
    
    try:
        # Get the new actual value from form
        new_value = Decimal(request.form['value'])
        
        # Convert projection to actual
        snapshot.is_projection = False
        snapshot.value = new_value
        snapshot.scenario_name = None
        snapshot.growth_rate_used = None
        
        # Recalculate growth percentage based on actual previous snapshot
        previous = PensionSnapshot.query.filter(
            PensionSnapshot.pension_id == pension_id,
            PensionSnapshot.review_date < snapshot.review_date,
            PensionSnapshot.is_projection == False
        ).order_by(PensionSnapshot.review_date.desc()).first()
        
        if previous and previous.value > 0:
            snapshot.growth_percent = ((new_value - previous.value) / previous.value) * 100
        else:
            snapshot.growth_percent = None
        
        # Update pension current value
        pension.current_value = new_value
        
        db.session.commit()
        
        # Regenerate future projections
        if Settings.get_value('auto_regenerate_projections', True):
            PensionService.save_projections(pension, scenario='default')
        
        flash(f'Snapshot confirmed with value £{new_value:,.2f}!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error confirming snapshot: {str(e)}', 'danger')
    
    return redirect(url_for('pensions.snapshots', id=pension_id))


@pensions_bp.route('/pensions/<int:pension_id>/snapshot/<int:snapshot_id>/delete', methods=['POST'])
def delete_snapshot(pension_id, snapshot_id):
    """Delete a snapshot"""
    pension = Pension.query.get_or_404(pension_id)
    snapshot = PensionSnapshot.query.get_or_404(snapshot_id)
    
    if snapshot.pension_id != pension_id:
        flash('Invalid snapshot for this pension.', 'danger')
        return redirect(url_for('pensions.snapshots', id=pension_id))
    
    try:
        db.session.delete(snapshot)
        db.session.commit()
        flash('Snapshot deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting snapshot: {str(e)}', 'danger')
    
    return redirect(url_for('pensions.snapshots', id=pension_id))


@pensions_bp.route('/pensions/projections')
def projections():
    """View comprehensive projections table (like Excel)"""
    person = request.args.get('person', None)
    scenario = request.args.get('scenario', 'default')
    
    # Get all active pensions
    query = Pension.query.filter_by(is_active=True)
    if person:
        query = query.filter_by(person=person)
    pensions = query.order_by(Pension.person, Pension.provider).all()
    
    # Get combined snapshots (historical + projected)
    combined_data = PensionService.get_combined_snapshots(person=person, scenario=scenario)
    
    # Get retirement summary
    retirement_summary = PensionService.get_retirement_summary(person=person)
    
    # Get unique people for filter
    people = db.session.query(Pension.person).distinct().order_by(Pension.person).all()
    people = [p[0] for p in people] if people else []
    
    return render_template('pensions/projections.html',
                         pensions=pensions,
                         combined_data=combined_data,
                         retirement_summary=retirement_summary,
                         people=people,
                         current_person=person,
                         current_scenario=scenario)


@pensions_bp.route('/pensions/generate-projections', methods=['POST'])
def generate_projections():
    """Generate/regenerate projections for all pensions"""
    scenario = request.form.get('scenario', 'default')
    
    try:
        count = PensionService.regenerate_all_projections(scenario=scenario)
        flash(f'Successfully generated {count} projection records for {scenario} scenario!', 'success')
    except Exception as e:
        flash(f'Error generating projections: {str(e)}', 'danger')
    
    return redirect(url_for('pensions.projections', scenario=scenario))


@pensions_bp.route('/pensions/<int:id>/generate-projection', methods=['POST'])
def generate_pension_projection(id):
    """Generate projections for a single pension"""
    pension = Pension.query.get_or_404(id)
    scenario = request.form.get('scenario', 'default')
    
    try:
        count = PensionService.save_projections(pension, scenario=scenario)
        flash(f'Generated {count} projection records for {pension.provider}!', 'success')
    except Exception as e:
        flash(f'Error generating projections: {str(e)}', 'danger')
    
    return redirect(url_for('pensions.snapshots', id=id))


@pensions_bp.route('/pensions/retirement-summary')
def retirement_summary():
    """Retirement planning dashboard"""
    person = request.args.get('person', None)
    
    summary = PensionService.get_retirement_summary(person=person)
    
    # Get age information
    people_info = []
    for p in ['Keiron', 'Emma']:
        age = PensionService.get_person_age(p)
        retirement_age = Settings.get_value(f'{p.lower()}_retirement_age', 65)
        months_remaining = PensionService.get_months_until_retirement(p, retirement_age)
        years_remaining = months_remaining / 12 if months_remaining else 0
        
        people_info.append({
            'name': p,
            'current_age': age,
            'retirement_age': retirement_age,
            'months_remaining': months_remaining,
            'years_remaining': years_remaining
        })
    
    return render_template('pensions/retirement_summary.html',
                         summary=summary,
                         people_info=people_info,
                         current_person=person)
