"""
Quick User Creation
Run from project root: python create_initial_users.py
"""
from app import create_app
from extensions import db
from models.users import User
from blueprints.auth.forms import validate_password_strength
import getpass


def create_initial_users():
    """Create two user accounts for household access"""
    app = create_app()
    
    with app.app_context():
        # Check if users already exist
        existing = User.query.count()
        if existing > 0:
            print(f"⚠️  {existing} user(s) already exist!")
            existing_emails = [u.email for u in User.query.all()]
            print(f"Existing users: {', '.join(existing_emails)}")
            response = input("\nCreate additional users? (y/n): ")
            if response.lower() != 'y':
                return
        
        print("\n=== Create User Accounts ===")
        print("\n🔒 Password Requirements:")
        print("   - At least 10 characters")
        print("   - Include uppercase and lowercase letters")
        print("   - Include at least one number")
        print("   - Include at least one special character (!@#$%^&*(),.?\":{}|<>)")
        print()
        
        # User 1
        print("User 1:")
        email1 = input("Email: ").strip().lower()
        name1 = input("Full Name: ").strip()
        
        # Password with validation
        while True:
            password1 = getpass.getpass("Password: ").strip()
            is_valid, error_msg = validate_password_strength(password1)
            if is_valid:
                password1_confirm = getpass.getpass("Confirm Password: ").strip()
                if password1 == password1_confirm:
                    break
                else:
                    print("❌ Passwords don't match. Try again.\n")
            else:
                print(f"❌ {error_msg}\n")
        
        user1 = User(email=email1, name=name1, is_active=True)
        user1.set_password(password1)
        db.session.add(user1)
        
        # User 2
        print("\nUser 2:")
        email2 = input("Email: ").strip().lower()
        name2 = input("Full Name: ").strip()
        
        # Password with validation
        while True:
            password2 = getpass.getpass("Password: ").strip()
            is_valid, error_msg = validate_password_strength(password2)
            if is_valid:
                password2_confirm = getpass.getpass("Confirm Password: ").strip()
                if password2 == password2_confirm:
                    break
                else:
                    print("❌ Passwords don't match. Try again.\n")
            else:
                print(f"❌ {error_msg}\n")
        
        user2 = User(email=email2, name=name2, is_active=True)
        user2.set_password(password2)
        db.session.add(user2)
        
        # Save
        try:
            db.session.commit()
            print(f"\n✅ Successfully created 2 users!")
            print(f"   - {name1} ({email1})")
            print(f"   - {name2} ({email2})")
            print("\n🔒 Login at: http://127.0.0.1:5000/login")
        except Exception as e:
            db.session.rollback()
            print(f"\n❌ Error: {e}")


if __name__ == '__main__':
    create_initial_users()
