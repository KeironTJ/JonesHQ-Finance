from flask import render_template, request, redirect, url_for, flash, jsonify
from . import pensions_bp
from models.pensions import Pension
from models.pension_snapshots import PensionSnapshot
from models.settings import Settings
from models.users import User
from services.planning.pension_service import PensionService
from extensions import db
from datetime import datetime
from decimal import Decimal
from utils.db_helpers import family_query, family_get, family_get_or_404, get_family_id
from services.household.member_identity_service import MemberIdentityService
from services.planning.retirement_service import RetirementService


def _get_pension_people():
    """Return a list of person names for pension forms, sourced from active family members."""
    seen = set()
    people = []
    for member in family_query(User).filter(User.is_active == True).all():
        name = (member.member_name or member.name or '').strip()
        if name and name not in seen:
            seen.add(name)
            people.append(name)
    # Fall back to names already stored in the database
    if not people:
        rows = family_query(Pension).with_entities(Pension.person).distinct().order_by(Pension.person).all()
        for row in rows:
            if row[0] and row[0] not in seen:
                seen.add(row[0])
                people.append(row[0])
    return people or ['Household']


@pensions_bp.route('/pensions')
def index():
    """List all pensions"""
    # Get filter parameter
    person = request.args.get('person', None)
    
    query = family_query(Pension)
    if person:
        query = query.filter_by(person=person)
    
    pensions = query.order_by(Pension.person, Pension.provider).all()
    
    # Get unique people for filter
    people = family_query(Pension).with_entities(Pension.person).distinct().order_by(Pension.person).all()
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
            pension = PensionService.create_pension(request.form)
            
            flash(f'Pension added successfully: {pension.provider}', 'success')
            return redirect(url_for('pensions.index'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error adding pension: {str(e)}', 'danger')
    
    return render_template('pensions/add.html', people=_get_pension_people(),
                           member_options=MemberIdentityService.options(), form=request.form)


@pensions_bp.route('/pensions/<int:id>/edit', methods=['GET', 'POST'])
def edit(id):
    """Edit a pension"""
    pension = family_get_or_404(Pension, id)
    
    if request.method == 'POST':
        try:
            pension = PensionService.update_pension(id, request.form)
            
            # Regenerate projections if auto-enabled
            if Settings.get_value('auto_regenerate_projections', True):
                PensionService.save_projections(pension, scenario='default')
            
            flash('Pension updated successfully!', 'success')
            return redirect(url_for('pensions.index'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating pension: {str(e)}', 'danger')
    
    return render_template('pensions/edit.html', pension=pension, people=_get_pension_people(),
                           member_options=MemberIdentityService.options(pension),
                           shared_retirement_age=RetirementService.age_for(
                               pension.person, pension.member_id,
                               default=67 if pension.member_id else pension.retirement_age or 67),
                           retirement_profile=RetirementService.profile(pension.person, pension.member_id),
                           form=request.form if request.method == 'POST' else None)


@pensions_bp.route('/pensions/<int:id>/retirement', methods=['POST'])
def save_retirement(id):
    pension = family_get_or_404(Pension, id)
    try:
        RetirementService.save(pension.person, request.form, pension.member_id)
        flash('Retirement profile updated for both planners. Regenerate pension projections to apply it.', 'success')
    except (ValueError, TypeError) as error:
        db.session.rollback()
        flash(str(error) or 'Unable to update retirement settings.', 'danger')
    return redirect(url_for('pensions.edit', id=id))


@pensions_bp.route('/pensions/<int:id>/delete', methods=['POST'])
def delete(id):
    """Delete a pension"""
    try:
        PensionService.delete_pension(id)
        flash('Pension deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting pension: {str(e)}', 'danger')
    
    return redirect(url_for('pensions.index'))


@pensions_bp.route('/pensions/<int:id>/snapshots')
def snapshots(id):
    """View snapshots for a pension"""
    pension = family_get_or_404(Pension, id)

    actual_snapshots = family_query(PensionSnapshot).filter(
        PensionSnapshot.pension_id == id,
        PensionSnapshot.is_projection == False
    ).order_by(PensionSnapshot.review_date.asc()).all()

    projected_snapshots = family_query(PensionSnapshot).filter(
        PensionSnapshot.pension_id == id,
        PensionSnapshot.is_projection == True
    ).order_by(PensionSnapshot.review_date.asc()).all()

    latest_actual = actual_snapshots[-1] if actual_snapshots else None

    return render_template('pensions/snapshots.html', pension=pension,
                           actual_snapshots=actual_snapshots,
                           projected_snapshots=projected_snapshots,
                           latest_actual=latest_actual)


@pensions_bp.route('/pensions/<int:id>/snapshots/add', methods=['GET', 'POST'])
def add_snapshot(id):
    """Add a snapshot for a pension"""
    pension = family_get_or_404(Pension, id)
    
    if request.method == 'POST':
        try:
            review_date = datetime.strptime(request.form['review_date'], '%Y-%m-%d').date()
            value = Decimal(request.form['value'])

            snapshot, growth_percent, pension = PensionService.add_actual_snapshot(
                id, review_date, value
            )
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
    pension = family_get_or_404(Pension, pension_id)
    snapshot = family_get_or_404(PensionSnapshot, snapshot_id)
    
    if snapshot.pension_id != pension_id:
        flash('Invalid snapshot for this pension.', 'danger')
        return redirect(url_for('pensions.snapshots', id=pension_id))
    
    try:
        # Get the new actual value from form
        new_value = Decimal(request.form['value'])
        
        pension = PensionService.confirm_snapshot(pension_id, snapshot_id, new_value)
        if pension is None:
            flash('Invalid snapshot for this pension.', 'danger')
            return redirect(url_for('pensions.snapshots', id=pension_id))
        
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
    pension = family_get_or_404(Pension, pension_id)
    snapshot = family_get_or_404(PensionSnapshot, snapshot_id)
    
    if snapshot.pension_id != pension_id:
        flash('Invalid snapshot for this pension.', 'danger')
        return redirect(url_for('pensions.snapshots', id=pension_id))
    
    try:
        PensionService.delete_snapshot(snapshot_id)
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
    query = family_query(Pension).filter_by(is_active=True)
    if person:
        query = query.filter_by(person=person)
    pensions = query.order_by(Pension.person, Pension.provider).all()
    
    # Get combined snapshots (historical + projected)
    combined_data = PensionService.get_combined_snapshots(person=person, scenario=scenario)
    
    # Get retirement summary
    retirement_summary = PensionService.get_retirement_summary(person=person)
    
    # Get unique people for filter
    people = family_query(Pension).with_entities(Pension.person).distinct().order_by(Pension.person).all()
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
    pension = family_get_or_404(Pension, id)
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
    identities = {(p.member_id, p.person) for p in family_query(Pension).all()}
    for member_id, p in sorted(identities, key=lambda item: (item[1], item[0] or 0)):
        age = PensionService.get_person_age(p, member_id)
        retirement_age = RetirementService.age_for(p, member_id)
        months_remaining = PensionService.get_months_until_retirement(p, retirement_age, member_id)
        years_remaining = months_remaining / 12 if months_remaining else 0
        
        people_info.append({
            'name': MemberIdentityService.label(p, member_id),
            'current_age': age,
            'retirement_age': retirement_age,
            'months_remaining': months_remaining,
            'years_remaining': years_remaining
        })
    
    return render_template('pensions/retirement_summary.html',
                         summary=summary,
                         people_info=people_info,
                         current_person=person)
