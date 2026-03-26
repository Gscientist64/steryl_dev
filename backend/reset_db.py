# STERYL_UP/reset_db.py
"""
Reset the database - USE WITH CAUTION!
"""
import sys
import os

# Add the current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app, db

def reset_database():
    """Reset the database"""
    app = create_app()
    
    with app.app_context():
        print("⚠️  WARNING: This will delete ALL data in the database!")
        confirm = input("Type 'yes' to confirm: ")
        
        if confirm.lower() == 'yes':
            print("Dropping all tables...")
            db.drop_all()
            
            print("Creating all tables...")
            db.create_all()
            
            print("✅ Database reset successfully!")
            print("\nYou can now register new users.")
        else:
            print("❌ Database reset cancelled.")

if __name__ == "__main__":
    reset_database()