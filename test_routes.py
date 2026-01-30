from app import app
from flask import url_for

with app.app_context():
    print("Vehicle routes:")
    print(f"  Overview: {url_for('vehicles.index')}")
    print(f"  Fuel Log: {url_for('vehicles.fuel')}")
    print(f"  Trip Log: {url_for('vehicles.trips')}")
    print(f"  Manage: {url_for('vehicles.manage')}")
    print("\nAll routes registered successfully!")
