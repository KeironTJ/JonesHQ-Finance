"""
Initialize the payday_day setting in the database
"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from app import create_app
from extensions import db
from models.settings import Settings

def main():
    """Initialize payday setting"""
    app = create_app()
    
    with app.app_context():
        # Check if setting exists
        existing = Settings.query.filter_by(key='payday_day').first()
        
        if existing:
            print(f"Payday setting already exists with value: {existing.value}")
        else:
            # Create the setting
            Settings.set_value(
                'payday_day',
                15,
                'Day of month when payday occurs (adjusted for weekends)',
                'int'
            )
            db.session.commit()
            print("✓ Payday setting created successfully with default value: 15")

if __name__ == '__main__':
    main()
