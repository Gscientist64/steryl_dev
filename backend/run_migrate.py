import psycopg2, os
from dotenv import load_dotenv
load_dotenv()

conn = psycopg2.connect(os.environ['DATABASE_URL'])
cur = conn.cursor()

sqls = [
    """CREATE TABLE IF NOT EXISTS distributor_request (
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
    )""",
    """CREATE TABLE IF NOT EXISTS hospital_request (
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
    )""",
    """CREATE TABLE IF NOT EXISTS hospital_request_item (
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
    )""",
]

for sql in sqls:
    cur.execute(sql)
    conn.commit()
    print(f"OK: {sql.split()[2]} {sql.split()[3]}")

# Also ensure request_id column exists on distributor_demand
cur.execute("ALTER TABLE distributor_demand ADD COLUMN IF NOT EXISTS request_id INTEGER")
cur.execute("""
    DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_distributor_demand_request_id') THEN
        ALTER TABLE distributor_demand ADD CONSTRAINT fk_distributor_demand_request_id
        FOREIGN KEY (request_id) REFERENCES distributor_request(id);
    END IF; END $$
""")
conn.commit()
print("OK: request_id column + FK constraint")

cur.close()
conn.close()
print("All migrations complete.")