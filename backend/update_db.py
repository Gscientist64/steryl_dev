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
        
        # Verify new tables were created
        updated_tables = inspector.get_table_names()
        logger.info(f"Tables after migration: {updated_tables}")
        
        if 'user_settings' in updated_tables:
            logger.info("✅ UserSettings table exists")
        else:
            logger.warning("⚠️ UserSettings table still missing - creating manually")
            # Create manually if needed
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
        
        logger.info("✅ Database migration completed!")

if __name__ == '__main__':
    migrate_database()