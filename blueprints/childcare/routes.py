from flask import render_template, request, redirect, url_for
from . import childcare_bp
from models.childcare import ChildcareRecord
from extensions import db


@childcare_bp.route('/childcare')
def index():
    """List all childcare records"""
    records = ChildcareRecord.query.all()
    return render_template('childcare/index.html', records=records)


@childcare_bp.route('/childcare/create', methods=['POST'])
def create():
    """Create a new childcare record"""
    # Implementation here
    return redirect(url_for('childcare.index'))
