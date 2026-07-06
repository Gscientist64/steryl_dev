"""Create missing tables and columns for multi-item request system."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app import create_app, db
from sqlalchemy import text

app = create_app()
with app.app_context():
    # Create all new model tables
    db.create_all()
    
    # Ensure request_id column on distributor_demand
    db.session.execute(text(
        "ALTER TABLE distributor_demand ADD COLUMN IF NOT EXISTS request_id INTEGER"
    ))
    db.session.execute(text(
        "DO $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_distributor_demand_request_id') THEN "
        "ALTER TABLE distributor_demand ADD CONSTRAINT fk_distributor_demand_request_id "
        "FOREIGN KEY (request_id) REFERENCES distributor_request(id); "
        "END IF; END $$"
    ))
    db.session.commit()
    print("Migration completed successfully.")