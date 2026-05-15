# create_manufacturer_data.py
from app import create_app, db
from app.models import User, Manufacturer, ProductSKU, Batch
from datetime import datetime, timedelta
import random

app = create_app()
with app.app_context():
    # Get or create test user
    user = User.query.filter_by(email='samuel@steryl.com').first()
    if not user:
        user = User.query.first()
    
    if user:
        # Create manufacturer profile
        manufacturer = Manufacturer.query.filter_by(user_id=user.id).first()
        if not manufacturer:
            manufacturer = Manufacturer(
                user_id=user.id,
                legal_entity_name="MedSupply Global",
                medical_license_number="REG-2024-001",
                business_address="123 Healthcare Ave, Lagos, Nigeria",
                verification_status="verified"
            )
            db.session.add(manufacturer)
            db.session.commit()
            print("✅ Manufacturer profile created")
        
        # Create sample products
        products_data = [
            {'name': 'CoviShield - V2 Protocol', 'sku': 'SKU-992-ALPHA', 'category': 'Vaccines', 'unit_price': 12500, 'reorder_level': 100},
            {'name': 'Insulin Pen - Rapid-Flow', 'sku': 'SKU-441-BETA', 'category': 'Diabetes Care', 'unit_price': 8500, 'reorder_level': 50},
            {'name': 'Oral Suspension 250mg', 'sku': 'SKU-202-GAMMA', 'category': 'Medications', 'unit_price': 3200, 'reorder_level': 200},
            {'name': 'CardioPlus T-Series', 'sku': 'SKU-105-DELTA', 'category': 'Cardiology', 'unit_price': 25000, 'reorder_level': 30},
        ]
        
        for p_data in products_data:
            existing = ProductSKU.query.filter_by(sku=p_data['sku']).first()
            if not existing:
                product = ProductSKU(
                    manufacturer_id=manufacturer.id,
                    name=p_data['name'],
                    sku=p_data['sku'],
                    category=p_data['category'],
                    unit_price=p_data['unit_price'],
                    reorder_level=p_data['reorder_level'],
                    status='active'
                )
                db.session.add(product)
        
        db.session.commit()
        print(f"✅ Created {len(products_data)} products")
        
        print("\n✅ Setup complete!")
        print(f"Manufacturer: {manufacturer.legal_entity_name}")
        print(f"Products: {ProductSKU.query.count()}")