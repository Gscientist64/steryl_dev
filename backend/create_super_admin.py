# create_super_admin.py
"""
Creates or resets the SUPER_ADMIN account.
Run once after first deployment: python create_super_admin.py
"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from app import create_app, db
from app.models import User

app = create_app()

with app.app_context():
    email = "admin@steryl.com"
    password = "SterylAdmin2024!"

    user = User.query.filter_by(email=email).first()

    if user:
        user.role = 'super_admin'
        user.account_status = 'approved'
        user.set_password(password)
        db.session.commit()
        print(f"[OK] Updated existing user to super_admin: {email}")
    else:
        user = User(
            first_name='Super',
            last_name='Admin',
            email=email,
            password=password,
            phone=None,
            country='Nigeria',
            account_type='hospital',
            organization_name='Steryl Platform',
        )
        user.role = 'super_admin'
        user.account_status = 'approved'
        db.session.add(user)
        db.session.commit()
        print("[OK] Super admin account created!")

    print()
    print("=" * 50)
    print("SUPER ADMIN LOGIN")
    print("=" * 50)
    print(f"   URL:      http://127.0.0.1:5003/login")
    print(f"   Email:    {email}")
    print(f"   Password: {password}")
    print("=" * 50)
    print()
    print("Admin panel: http://127.0.0.1:5003/admin/registrations")
    print("CHANGE THIS PASSWORD immediately after first login.")
