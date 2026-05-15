# add_sample_data.py
from app import create_app, db
from app.models import SyncQueue, Shipment, ShipmentItem, BudgetCategory
from datetime import datetime, timedelta
import json

app = create_app()
with app.app_context():
    # Add sample sync queue items
    if SyncQueue.query.count() == 0:
        sync_items = [
            SyncQueue(action_type='stock_adjustment', description='Inventory update for Amoxicillin (Batch #AX-992)', status='pending', created_at=datetime.now()),
            SyncQueue(action_type='order_submission', description='Order #8829 - MedSource Procurement', status='failed', error_message="Error: Field 'hospital_id' is mandatory", created_at=datetime.now()),
            SyncQueue(action_type='batch_scan', description='Warehouse A - Bulk receipt of surgical kits', status='pending', created_at=datetime.now()),
            SyncQueue(action_type='returns_processing', description='Returned 14 expired units to central pharmacy', status='pending', created_at=datetime.now())
        ]
        for item in sync_items:
            db.session.add(item)
        db.session.commit()
        print("✅ Added sync queue data")
    
    # Add sample budget categories
    if BudgetCategory.query.count() == 0:
        current_month = datetime.now().month
        current_year = datetime.now().year
        categories = [
            BudgetCategory(name='Consumables', allocated=45000, spent=18450, month=current_month, year=current_year),
            BudgetCategory(name='Reagents & Chemicals', allocated=30000, spent=12300, month=current_month, year=current_year),
            BudgetCategory(name='Lab Equipment', allocated=25000, spent=9250, month=current_month, year=current_year),
            BudgetCategory(name='Pharmacy Stocks', allocated=20000, spent=5000, month=current_month, year=current_year)
        ]
        for cat in categories:
            db.session.add(cat)
        db.session.commit()
        print("✅ Added budget data")
    
    print("✅ All sample data added successfully!")