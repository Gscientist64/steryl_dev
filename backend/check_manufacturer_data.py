# check_manufacturer_data.py
from app import create_app, db
from app.models import User, Manufacturer, ProductSKU

app = create_app()
with app.app_context():
    # Find the manufacturer user
    user = User.query.filter_by(email='manufacturer@steryl.com').first()
    if not user:
        print("❌ Manufacturer user not found. Please run create_manufacturer_user.py first.")
        exit()

    print(f"✅ Manufacturer user found: {user.email} (ID: {user.id})")

    # Check manufacturer profile
    manufacturer = Manufacturer.query.filter_by(user_id=user.id).first()
    if not manufacturer:
        print("❌ No manufacturer profile linked to this user.")
        print("   Creating one now...")
        manufacturer = Manufacturer(
            user_id=user.id,
            legal_entity_name="Steryl Manufacturing Co.",
            medical_license_number="REG-MFG-2024-001",
            verification_status="verified"
        )
        db.session.add(manufacturer)
        db.session.commit()
        print("✅ Manufacturer profile created.")
    else:
        print(f"✅ Manufacturer profile found: {manufacturer.legal_entity_name} (ID: {manufacturer.id})")

    # Check products linked to this manufacturer
    products = ProductSKU.query.filter_by(manufacturer_id=manufacturer.id).all()
    if not products:
        print("❌ No ProductSKU records linked to this manufacturer.")
        print("   Adding sample products...")
        sample_products = [
            ProductSKU(
                manufacturer_id=manufacturer.id,
                name="Steryl-Vax B12",
                sku="SV-992-X",
                category="Vaccines",
                unit_price=12500.00,
                reorder_level=100,
                status="active"
            ),
            ProductSKU(
                manufacturer_id=manufacturer.id,
                name="Cipro-Health Pro",
                sku="CH-441-A",
                category="Antibiotics",
                unit_price=3200.00,
                reorder_level=50,
                status="active"
            ),
            ProductSKU(
                manufacturer_id=manufacturer.id,
                name="Neo-Genic Serum",
                sku="NG-210-B",
                category="Biologics",
                unit_price=8500.00,
                reorder_level=30,
                status="active"
            )
        ]
        for p in sample_products:
            db.session.add(p)
        db.session.commit()
        print(f"✅ Added {len(sample_products)} sample products.")
    else:
        print(f"✅ Found {len(products)} products linked to this manufacturer:")
        for p in products:
            print(f"   - {p.name} ({p.sku})")