"""
Initialize database and create tables
Run this script once to set up your database
"""

from app import create_app
from extensions import db

def init_db():
    """Initialize the database"""
    app = create_app('development')
    
    with app.app_context():
        print("Creating database tables...")
        db.create_all()
        print("✓ Database tables created successfully!")
        print(f"Database location: {app.config['SQLALCHEMY_DATABASE_URI']}")
        
        # Print all tables
        print("\nTables created:")
        for table in db.metadata.sorted_tables:
            print(f"  - {table.name}")

if __name__ == '__main__':
    init_db()
