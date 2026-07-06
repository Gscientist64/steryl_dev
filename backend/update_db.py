# migrate_db.py
"""
Safe database migration script
"""
from app import create_app, db
from sqlalchemy import text, inspect
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def migrate_database():
    app = create_app()
    with app.app_context():
        inspector = inspect(db.engine)
        existing_tables = inspector.get_table_names()

        logger.info(f"Existing tables: {existing_tables}")

        # Create missing tables without dropping existing ones
        db.create_all()

        # ── User table: new columns for unified registration + approval workflow ──
        if 'user' in existing_tables:
            user_cols = {c['name'] for c in inspector.get_columns('user')}
            new_user_cols = {
                'organization_name':  "ALTER TABLE \"user\" ADD COLUMN IF NOT EXISTS organization_name VARCHAR(200)",
                'license_number':     "ALTER TABLE \"user\" ADD COLUMN IF NOT EXISTS license_number VARCHAR(100)",
                'business_address':   "ALTER TABLE \"user\" ADD COLUMN IF NOT EXISTS business_address TEXT",
                'account_status':     "ALTER TABLE \"user\" ADD COLUMN IF NOT EXISTS account_status VARCHAR(20) DEFAULT 'pending' NOT NULL",
                'rejection_reason':   "ALTER TABLE \"user\" ADD COLUMN IF NOT EXISTS rejection_reason TEXT",
                'reviewed_by':        "ALTER TABLE \"user\" ADD COLUMN IF NOT EXISTS reviewed_by INTEGER",
                'reviewed_at':        "ALTER TABLE \"user\" ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMP",
            }
            for col, sql in new_user_cols.items():
                if col not in user_cols:
                    try:
                        db.session.execute(text(sql))
                        db.session.commit()
                        logger.info(f"✅ Added user.{col}")
                    except Exception as e:
                        db.session.rollback()
                        logger.warning(f"Could not add user.{col}: {e}")

            # Back-fill: existing users that have no account_status should default to 'approved'
            # so current users aren't locked out
            try:
                db.session.execute(text(
                    "UPDATE \"user\" SET account_status = 'approved' WHERE account_status IS NULL OR account_status = ''"
                ))
                db.session.commit()
                logger.info("✅ Back-filled account_status='approved' for existing users")
            except Exception as e:
                db.session.rollback()
                logger.warning(f"Back-fill account_status skipped: {e}")
        
        # Verify new tables were created
        updated_tables = inspector.get_table_names()
        logger.info(f"Tables after migration: {updated_tables}")
        
        if 'user_settings' in updated_tables:
            logger.info("✅ UserSettings table exists")
        else:
            logger.warning("⚠️ UserSettings table still missing - creating manually")
            try:
                db.session.execute(text("""
                    CREATE TABLE IF NOT EXISTS user_settings (
                        id SERIAL PRIMARY KEY,
                        user_id INTEGER NOT NULL UNIQUE REFERENCES "user"(id),
                        theme VARCHAR(20) DEFAULT 'light',
                        primary_color VARCHAR(20) DEFAULT 'teal',
                        font_size VARCHAR(10) DEFAULT 'medium',
                        reduced_motion BOOLEAN DEFAULT FALSE,
                        email_notifications BOOLEAN DEFAULT TRUE,
                        push_notifications BOOLEAN DEFAULT TRUE,
                        low_stock_alerts BOOLEAN DEFAULT TRUE,
                        order_updates BOOLEAN DEFAULT TRUE,
                        approval_reminders BOOLEAN DEFAULT TRUE,
                        compact_view BOOLEAN DEFAULT FALSE,
                        show_dashboard_widgets BOOLEAN DEFAULT TRUE,
                        default_dashboard_view VARCHAR(20) DEFAULT 'grid',
                        share_analytics BOOLEAN DEFAULT FALSE,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """))
                db.session.commit()
                logger.info("✅ UserSettings table created manually")
            except Exception as e:
                logger.error(f"Error creating table: {e}")
        
        if 'account_upgrade_request' in updated_tables:
            logger.info("✅ AccountUpgradeRequest table exists")
        else:
            logger.warning("⚠️ AccountUpgradeRequest table still missing - creating manually")
            try:
                db.session.execute(text("""
                    CREATE TABLE IF NOT EXISTS account_upgrade_request (
                        id SERIAL PRIMARY KEY,
                        user_id INTEGER NOT NULL REFERENCES "user"(id),
                        requested_account_type VARCHAR(50) NOT NULL,
                        current_account_type VARCHAR(50) NOT NULL,
                        reason TEXT,
                        status VARCHAR(20) DEFAULT 'pending',
                        reviewed_by INTEGER REFERENCES "user"(id),
                        reviewed_at TIMESTAMP,
                        rejection_reason TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """))
                db.session.commit()
                logger.info("✅ AccountUpgradeRequest table created manually")
            except Exception as e:
                logger.error(f"Error creating table: {e}")

        # ── DistributorInventory new columns ──────────────────────────────────
        if 'distributor_inventory' in updated_tables:
            inv_cols = {c['name'] for c in inspector.get_columns('distributor_inventory')}
            new_inv_cols = {
                'selling_price':    'ALTER TABLE distributor_inventory ADD COLUMN IF NOT EXISTS selling_price FLOAT',
                'batch_number':     'ALTER TABLE distributor_inventory ADD COLUMN IF NOT EXISTS batch_number VARCHAR(50)',
                'manufactured_date':'ALTER TABLE distributor_inventory ADD COLUMN IF NOT EXISTS manufactured_date DATE',
                'expiry_date':      'ALTER TABLE distributor_inventory ADD COLUMN IF NOT EXISTS expiry_date DATE',
                'batch_location':   'ALTER TABLE distributor_inventory ADD COLUMN IF NOT EXISTS batch_location VARCHAR(100)',
            }
            for col, sql in new_inv_cols.items():
                if col not in inv_cols:
                    try:
                        db.session.execute(text(sql))
                        db.session.commit()
                        logger.info(f"✅ Added distributor_inventory.{col}")
                    except Exception as e:
                        db.session.rollback()
                        logger.warning(f"Could not add distributor_inventory.{col}: {e}")

        # ── New multi-item request tables ──────────────────────────────────
        new_tables = {
            'distributor_request': """
                CREATE TABLE IF NOT EXISTS distributor_request (
                    id SERIAL PRIMARY KEY,
                    request_number VARCHAR(50) UNIQUE NOT NULL,
                    distributor_user_id INTEGER NOT NULL REFERENCES "user"(id),
                    manufacturer_id INTEGER NOT NULL REFERENCES manufacturer(id),
                    status VARCHAR(20) DEFAULT 'pending',
                    payment_status VARCHAR(20) DEFAULT 'pending',
                    notes TEXT,
                    total_amount FLOAT DEFAULT 0,
                    item_count INTEGER DEFAULT 0,
                    requested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    payment_validated_at TIMESTAMP,
                    approved_at TIMESTAMP,
                    supplied_at TIMESTAMP,
                    completed_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """,
            'hospital_request': """
                CREATE TABLE IF NOT EXISTS hospital_request (
                    id SERIAL PRIMARY KEY,
                    request_number VARCHAR(50) UNIQUE NOT NULL,
                    hospital_user_id INTEGER NOT NULL REFERENCES "user"(id),
                    distributor_user_id INTEGER NOT NULL REFERENCES "user"(id),
                    status VARCHAR(20) DEFAULT 'pending',
                    notes TEXT,
                    total_amount FLOAT DEFAULT 0,
                    item_count INTEGER DEFAULT 0,
                    requested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    approved_at TIMESTAMP,
                    supplied_at TIMESTAMP,
                    completed_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """,
            'hospital_request_item': """
                CREATE TABLE IF NOT EXISTS hospital_request_item (
                    id SERIAL PRIMARY KEY,
                    request_id INTEGER NOT NULL REFERENCES hospital_request(id),
                    distributor_user_id INTEGER NOT NULL REFERENCES "user"(id),
                    manufacturer_id INTEGER NOT NULL REFERENCES manufacturer(id),
                    product_sku_id INTEGER NOT NULL REFERENCES product_sku(id),
                    requested_quantity INTEGER NOT NULL,
                    approved_quantity INTEGER DEFAULT 0,
                    supplied_quantity INTEGER DEFAULT 0,
                    unit_price FLOAT DEFAULT 0,
                    subtotal FLOAT DEFAULT 0,
                    status VARCHAR(20) DEFAULT 'pending',
                    notes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """,
        }
        for tbl_name, ddl in new_tables.items():
            if tbl_name not in updated_tables:
                try:
                    db.session.execute(text(ddl))
                    db.session.commit()
                    logger.info(f"✅ Table {tbl_name} created")
                except Exception as e:
                    db.session.rollback()
                    logger.warning(f"Could not create {tbl_name}: {e}")

        # ── distributor_demand.request_id column ──────────────────────────
        if 'distributor_demand' in updated_tables:
            dd_cols = {c['name'] for c in inspector.get_columns('distributor_demand')}
            if 'request_id' not in dd_cols:
                try:
                    db.session.execute(text("ALTER TABLE distributor_demand ADD COLUMN IF NOT EXISTS request_id INTEGER"))
                    db.session.execute(text("DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_distributor_demand_request_id') THEN ALTER TABLE distributor_demand ADD CONSTRAINT fk_distributor_demand_request_id FOREIGN KEY (request_id) REFERENCES distributor_request(id); END IF; END $$"))
                    db.session.commit()
                    logger.info("✅ Added distributor_demand.request_id")
                except Exception as e:
                    db.session.rollback()
                    logger.warning(f"Could not add request_id: {e}")

        logger.info("✅ Database migration completed!")

if __name__ == '__main__':
    migrate_database()