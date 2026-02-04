"""
Create Users Script
Creates initial user accounts for accessing the application
"""
import sys
import os

# Add the project root to the path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, project_root)

from app import create_app
from extensions import db
from models.users import User


def create_users():
    """Create initial user accounts"""
    app = create_app()
    
    with app.app_context():
        # Check if users already exist
        existing_users = User.query.count()
        if existing_users > 0:
            print(f"⚠️  Warning: {existing_users} user(s) already exist in database.")
            response = input("Continue and create additional users? (yes/no): ")
            if response.lower() not in ['yes', 'y']:
                print("Aborted.")
                return
        
        users_to_create = []
        
        print("\n=== Create User Accounts ===\n")
        
        while True:
            print("\nEnter user details (or press Enter on email to finish):")
            email = input("Email: ").strip().lower()
            
            if not email:
                break
            
            # Check if user already exists
            existing = User.query.filter_by(email=email).first()
            if existing:
                print(f"❌ User with email '{email}' already exists!")
                continue
            
            name = input("Full Name: ").strip()
            password = input("Password: ").strip()
            confirm_password = input("Confirm Password: ").strip()
            
            if password != confirm_password:
                print("❌ Passwords don't match!")
                continue
            
            if len(password) < 8:
                print("❌ Password must be at least 8 characters!")
                continue
            
            users_to_create.append({
                'email': email,
                'name': name,
                'password': password
            })
            
            print(f"✅ User '{name}' ({email}) queued for creation")
        
        if not users_to_create:
            print("\nNo users to create. Exiting.")
            return
        
        # Create users
        print(f"\nCreating {len(users_to_create)} user(s)...")
        
        for user_data in users_to_create:
            user = User(
                email=user_data['email'],
                name=user_data['name'],
                is_active=True
            )
            user.set_password(user_data['password'])
            db.session.add(user)
        
        try:
            db.session.commit()
            print(f"\n✅ Successfully created {len(users_to_create)} user(s)!")
            print("\n📋 Created users:")
            for user_data in users_to_create:
                print(f"   - {user_data['name']} ({user_data['email']})")
            print("\n🔒 You can now log in at: http://127.0.0.1:5000/login")
        except Exception as e:
            db.session.rollback()
            print(f"\n❌ Error creating users: {e}")


if __name__ == '__main__':
    create_users()
