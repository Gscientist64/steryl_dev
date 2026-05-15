# add_sync_data.py
from app import create_app, db
from app.models import SyncQueue
from datetime import datetime

app = create_app()
with app.app_context():
    # Add sample sync queue items if none exist
    if SyncQueue.query.count() == 0:
        sync_items = [
            SyncQueue(
                action_type='stock_adjustment',
                description='Inventory update for Amoxicillin (Batch #AX-992)',
                status='pending',
                created_at=datetime.now()
            ),
            SyncQueue(
                action_type='order_submission',
                description='Order #8829 - MedSource Procurement',
                status='failed',
                error_message="Error: Field 'hospital_id' is mandatory",
                created_at=datetime.now()
            ),
            SyncQueue(
                action_type='batch_scan',
                description='Warehouse A - Bulk receipt of surgical kits',
                status='pending',
                created_at=datetime.now()
            ),
            SyncQueue(
                action_type='returns_processing',
                description='Returned 14 expired units to central pharmacy',
                status='pending',
                created_at=datetime.now()
            )
        ]
        for item in sync_items:
            db.session.add(item)
        db.session.commit()
        print("✅ Sync queue data added!")