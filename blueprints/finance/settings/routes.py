from flask import abort, current_app, flash, redirect, render_template, request, url_for
from decimal import InvalidOperation
from sqlalchemy.exc import SQLAlchemyError
from services.finance.finance_access_service import FinanceAccessService
from utils.permissions import SECTION_GROUPS, SECTION_LABELS
from utils.reauth import recent_auth_required

from . import settings_bp
from extensions import db
from models.tax_settings import TaxSettings
from services.finance.settings_service import SettingsService
from utils.db_helpers import family_get_or_404, family_query


@settings_bp.route('/settings')
def index():
    return render_template('settings/index.html')


@settings_bp.route('/settings/overview')
def overview():
    return render_template('settings/overview.html')


@settings_bp.route('/settings/access')
def finance_access():
    return render_template(
        'settings/access.html', **FinanceAccessService.get_page_data(),
        section_groups=SECTION_GROUPS, section_labels=SECTION_LABELS,
    )


@settings_bp.route('/settings/access/members/<int:member_id>', methods=['POST'])
@recent_auth_required
def update_finance_access(member_id):
    try:
        member = FinanceAccessService.update_member(member_id, {
            'member_name': request.form.get('member_name'),
            'sections': request.form.getlist('sections'),
        })
    except (ValueError, TypeError) as error:
        db.session.rollback()
        flash(str(error) or 'Invalid Finance access settings.', 'danger')
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception('Unable to update Finance access')
        flash('Unable to update Finance access. Please try again.', 'danger')
    else:
        flash(f'Updated Finance access for {member.name}.', 'success')
    return redirect(url_for('settings.finance_access'))


@settings_bp.route('/settings/modules/<section>', methods=['GET', 'POST'])
def module_settings(section):
    if section not in SettingsService.SECTIONS:
        abort(404)
    if request.method == 'POST':
        try:
            SettingsService.update_section(section, request.form)
            flash(f'{SettingsService.SECTIONS[section][0]} settings saved.', 'success')
            return redirect(url_for('settings.module_settings', section=section))
        except (ValueError, TypeError) as error:
            db.session.rollback()
            flash(str(error) or 'Invalid setting value.', 'danger')
        except SQLAlchemyError:
            db.session.rollback()
            current_app.logger.exception('Unable to update %s settings', section)
            flash('Unable to save settings. Please try again.', 'danger')
    context = SettingsService.get_section_data(section)
    if request.method == 'POST':
        context['values'] = request.form
    return render_template(f'settings/{section}.html', **context)


@settings_bp.route('/settings/update', methods=['POST'])
def update():
    flash('Settings now save independently. Please open the relevant settings page.', 'warning')
    return redirect(url_for('settings.index'))


@settings_bp.route('/settings/save_preference', methods=['POST'])
def save_preference():
    # Preserve the legacy endpoint for existing clients; writes are now personal.
    from blueprints.finance.preferences.routes import save_preference as save_personal_preference
    return save_personal_preference()


@settings_bp.route('/settings/tax')
def tax_settings():
    tax_years = family_query(TaxSettings).order_by(TaxSettings.effective_from.desc()).all()
    return render_template('settings/tax_settings.html', tax_years=tax_years)


@settings_bp.route('/settings/tax/<int:id>/edit', methods=['GET', 'POST'])
def edit_tax_settings(id):
    tax_year = family_get_or_404(TaxSettings, id)
    if request.method == 'POST':
        try:
            tax_year = SettingsService.update_tax_settings(id, request.form)
            flash(f'Tax settings for {tax_year.tax_year} updated successfully!', 'success')
            return redirect(url_for('settings.tax_settings'))
        except (ValueError, TypeError, KeyError, InvalidOperation) as error:
            db.session.rollback()
            flash(str(error) or 'Invalid tax setting value.', 'danger')
        except SQLAlchemyError:
            db.session.rollback()
            current_app.logger.exception('Unable to update tax settings')
            flash('Unable to update tax settings. Please try again.', 'danger')
    return render_template('settings/edit_tax_settings.html', tax_year=tax_year)
