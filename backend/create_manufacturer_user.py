# create_manufacturer_user.py
from app import create_app, db
from app.models import User, Manufacturer
from flask_bcrypt import Bcrypt

app = create_app()
bcrypt = Bcrypt(app)

with app.app_context():
    print("Creating test manufacturer account...")
    
    # Test credentials
    email = "manufacturer@steryl.com"
    password = "Manufacturer123!"
    
    # Check if user already exists
    existing_user = User.query.filter_by(email=email).first()
    
    if existing_user:
        print(f"User already exists: {email}")
        # Update password if needed
        existing_user.set_password(password)
        existing_user.account_type = 'manufacturer'
        db.session.commit()
        print(f"✅ Updated account for: {email}")
    else:
        user = User(
            first_name='Manufacturer',
            last_name='Admin',
            email=email,
            password=password,
            phone='+1234567890',
            country='Nigeria',
            account_type='manufacturer'
        )
        db.session.add(user)
        db.session.flush()
        
        # Create manufacturer profile
        manufacturer = Manufacturer(
            user_id=user.id,
            legal_entity_name='Steryl Manufacturing Co.',
            medical_license_number='REG-MFG-2024-001',
            business_address='123 Industrial Park, Lagos, Nigeria',
            verification_status='verified'
        )
        db.session.add(manufacturer)
        db.session.commit()
        
        print(f"✅ Manufacturer account created!")
    
    print("\n" + "=" * 50)
    print("MANUFACTURER LOGIN CREDENTIALS")
    print("=" * 50)
    print(f"   Email: {email}")
    print(f"   Password: {password}")
    print("=" * 50)
    print("\nLogin at: http://127.0.0.1:5003/manufacturer/login")