from flask import render_template, request, redirect, url_for
from . import vehicles_bp
from models.vehicles import Vehicle
from extensions import db


@vehicles_bp.route('/vehicles')
def index():
    """List all vehicles"""
    vehicles = Vehicle.query.all()
    return render_template('vehicles/index.html', vehicles=vehicles)


@vehicles_bp.route('/vehicles/create', methods=['POST'])
def create():
    """Create a new vehicle"""
    # Implementation here
    return redirect(url_for('vehicles.index'))
