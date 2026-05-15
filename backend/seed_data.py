# STERYL_UP/seed_data.py
"""
Seed database with initial data
"""
from app import create_app, db
from app.models import User, Category, Product, Batch, Order, OrderItem, StockMovement
from datetime import datetime, timedelta
import random

def seed_database():
    app = create_app()
    with app.app_context():
        try:
            # Clear existing data
            print("Clearing existing data...")
            db.drop_all()
            db.create_all()
            print("Database tables created.")
            
            # Create admin user
            print("Creating users...")
            admin = User(
                first_name='Admin',
                last_name='User',
                email='admin@steryl.com',
                password='Admin123!',
                phone='+1234567890',
                country='Nigeria',
                account_type='hospital'
            )
            admin.department = 'Administration'
            admin.role = 'admin'
            admin.spend_limit = 100000
            db.session.add(admin)
            
            # Create regular user
            user = User(
                first_name='Dr.',
                last_name='Samuel',
                email='samuel@steryl.com',
                password='Password123!',
                phone='+2348123456789',
                country='Nigeria',
                account_type='hospital'
            )
            user.department = 'Pharmacy'
            user.role = 'procurement_officer'
            user.spend_limit = 50000
            db.session.add(user)
            
            db.session.flush()
            
            # Create categories
            print("Creating categories...")
            categories = [
                Category(name='Medications', description='Pharmaceutical drugs and medicines'),
                Category(name='Surgical Supplies', description='Surgical instruments and supplies'),
                Category(name='Diagnostic', description='Diagnostic equipment and reagents'),
                Category(name='Protective Equipment', description='PPE and safety gear'),
                Category(name='Lab Supplies', description='Laboratory consumables')
            ]
            
            for cat in categories:
                db.session.add(cat)
            
            db.session.flush()
            
            # Create products
            print("Creating products...")
            products_data = [
                {'name': 'Paracetamol 500mg', 'sku': 'MED-PCM-001', 'category': 'Medications', 'unit_price': 1200.00, 'reorder_level': 100, 'description': 'Pack of 100 tablets'},
                {'name': 'Amoxicillin 500mg', 'sku': 'MED-AMX-001', 'category': 'Medications', 'unit_price': 2500.00, 'reorder_level': 80, 'description': 'Broad-spectrum antibiotic'},
                {'name': 'Sterile Gauze Pads', 'sku': 'SUR-GZ-001', 'category': 'Surgical Supplies', 'unit_price': 850.00, 'reorder_level': 50, 'description': 'Box of 50, sterile'},
                {'name': 'Nitrile Gloves (M)', 'sku': 'PPE-GL-001', 'category': 'Protective Equipment', 'unit_price': 4500.00, 'reorder_level': 30, 'description': 'Case of 10 boxes'},
                {'name': 'Surgical Gloves (M)', 'sku': 'PPE-SG-001', 'category': 'Protective Equipment', 'unit_price': 5500.00, 'reorder_level': 40, 'description': 'Sterile surgical gloves'},
                {'name': 'Saline Bags 500ml', 'sku': 'MED-SAL-001', 'category': 'Medications', 'unit_price': 800.00, 'reorder_level': 80, 'description': 'IV saline solution'},
                {'name': 'Ceftriaxone 1g', 'sku': 'MED-CEF-001', 'category': 'Medications', 'unit_price': 3500.00, 'reorder_level': 60, 'description': 'Antibiotic injection'},
                {'name': 'Diagnostic Reagents', 'sku': 'LAB-DIAG-001', 'category': 'Diagnostic', 'unit_price': 12500.00, 'reorder_level': 20, 'description': 'Blood test reagents kit'},
                {'name': 'Latex Gloves L', 'sku': 'PPE-LT-001', 'category': 'Protective Equipment', 'unit_price': 4200.00, 'reorder_level': 35, 'description': 'Powder-free latex gloves'}
            ]

            
            products = []
            for p_data in products_data:
                category = Category.query.filter_by(name=p_data['category']).first()
                product = Product(
                    name=p_data['name'],
                    sku=p_data['sku'],
                    category_id=category.id if category else None,
                    unit_price=p_data['unit_price'],
                    reorder_level=p_data['reorder_level'],
                    description=p_data.get('description', '')
                )
                db.session.add(product)
                products.append(product)
            
            db.session.flush()
            
            # Create batches with stock
            print("Creating batches...")
            batch_data = [
                {'product': 'Paracetamol 500mg', 'batch': 'B2405-01', 'quantity': 450, 'expiry': '2026-12-31', 'location': 'Ward B - Shelf 4'},
                {'product': 'Amoxicillin 500mg', 'batch': 'B2405-02', 'quantity': 45, 'expiry': '2026-10-15', 'location': 'Pharmacy A'},
                {'product': 'Sterile Gauze Pads', 'batch': 'B2404-01', 'quantity': 200, 'expiry': '2026-08-20', 'location': 'Surgical Storage'},
                {'product': 'Nitrile Gloves (M)', 'batch': 'B2403-01', 'quantity': 450, 'expiry': '2027-01-15', 'location': 'PPE Storage'},
                {'product': 'Surgical Gloves (M)', 'batch': 'B2402-01', 'quantity': 12, 'expiry': '2026-09-10', 'location': 'Surgical Suite'},
                {'product': 'Saline Bags 500ml', 'batch': 'B2405-03', 'quantity': 82, 'expiry': '2026-11-30', 'location': 'IV Storage'},
                {'product': 'Ceftriaxone 1g', 'batch': 'B2401-01', 'quantity': 150, 'expiry': '2026-12-01', 'location': 'Refrigerator A'},
                {'product': 'Diagnostic Reagents', 'batch': 'B2404-02', 'quantity': 45, 'expiry': '2026-07-15', 'location': 'Lab Storage'},
                {'product': 'Latex Gloves L', 'batch': 'B2403-02', 'quantity': 200, 'expiry': '2027-02-28', 'location': 'PPE Storage'}
            ]
            
            for b_data in batch_data:
                product = Product.query.filter_by(name=b_data['product']).first()
                if product:
                    batch = Batch(
                        batch_number=b_data['batch'],
                        product_id=product.id,
                        quantity=b_data['quantity'],
                        expiry_date=datetime.strptime(b_data['expiry'], '%Y-%m-%d').date(),
                        location=b_data['location'],
                        status='active',
                        is_verified=True
                    )
                    db.session.add(batch)
            
            db.session.commit()
            
            # Create pending orders for approval
            print("Creating orders...")
            for i in range(3):
                order = Order(
                    order_number=f"ORD-{datetime.now().strftime('%Y%m%d')}-{i+1}",
                    requester_id=user.id,
                    order_type='purchase',
                    status='pending',
                    priority=['normal', 'high', 'urgent'][i % 3],
                    notes=f"Order {i+1} - {'Urgent' if i == 1 else 'Regular'} restock needed",
                    total_amount=random.choice([4200, 850, 12480])
                )
                db.session.add(order)
                db.session.flush()
                
                # Add items to order
                product = random.choice(products)
                item = OrderItem(
                    order_id=order.id,
                    product_id=product.id,
                    quantity=random.randint(10, 50),
                    unit_price=product.unit_price
                )
                item.calculate_subtotal()
                db.session.add(item)
            
            db.session.commit()
            
            print("\n" + "="*50)
            print("✅ Database seeded successfully!")
            print("="*50)
            print(f"Created: {User.query.count()} users")
            print(f"Created: {Category.query.count()} categories")
            print(f"Created: {Product.query.count()} products")
            print(f"Created: {Batch.query.count()} batches")
            print(f"Created: {Order.query.count()} orders")
            print("\n📝 Test Credentials:")
            print("   Admin: admin@steryl.com / Admin123!")
            print("   User:  samuel@steryl.com / Password123!")
            print("="*50)
            
        except Exception as e:
            print(f"\n❌ Error seeding database: {str(e)}")
            db.session.rollback()
            raise e

if __name__ == '__main__':
    seed_database()