# setup_postgresql.py
"""
Complete setup for PostgreSQL database
"""
from app import create_app, db
from sqlalchemy import text
import sys

def setup_database():
    app = create_app()
    with app.app_context():
        print("=" * 60)
        print("Setting up PostgreSQL Database")
        print("=" * 60)
        
        # Show current database URL
        db_url = app.config['SQLALCHEMY_DATABASE_URI']
        print(f"\n📊 Database URL: {db_url}")
        
        if 'postgresql' not in db_url:
            print("❌ ERROR: Not using PostgreSQL! Check your .env file.")
            print("   DATABASE_URL should be: postgresql://postgres:lamis@localhost:5432/steryl_db")
            sys.exit(1)
        
        # Test connection
        try:
            db.session.execute(text("SELECT 1"))
            print("✅ PostgreSQL connection successful!")
        except Exception as e:
            print(f"❌ Connection failed: {e}")
            sys.exit(1)
        
        # Reset database
        print("\n⚠️  This will delete ALL existing data!")
        confirm = input("Type 'yes' to continue: ")
        
        if confirm.lower() == 'yes':
            # Drop all tables
            print("\nDropping all tables...")
            db.session.execute(text("DROP SCHEMA public CASCADE"))
            db.session.execute(text("CREATE SCHEMA public"))
            db.session.commit()
            
            # Create all tables
            print("Creating all tables with new schema...")
            db.create_all()
            
            print("✅ Database schema created successfully!")
            
            # Now seed the data
            print("\n🌱 Seeding database with sample data...")
            from seed_data import seed_database
            seed_database()
            
            print("\n" + "=" * 60)
            print("✅ Setup complete!")
            print("=" * 60)
            print("\n📝 Test Credentials:")
            print("   Admin: admin@steryl.com / Admin123!")
            print("   User:  samuel@steryl.com / Password123!")
            print("\n🔗 Login URL: http://127.0.0.1:5003/login")
            print("\n💡 Tip: Use incognito/private window to avoid session issues")
        else:
            print("❌ Setup cancelled.")

if __name__ == '__main__':
    setup_database()