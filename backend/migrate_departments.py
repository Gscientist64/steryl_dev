import psycopg2, os
from dotenv import load_dotenv
load_dotenv()

conn = psycopg2.connect(os.environ['DATABASE_URL'])
cur = conn.cursor()

migrations = [
    ("create department table", """
        CREATE TABLE IF NOT EXISTS department (
            id SERIAL PRIMARY KEY,
            name VARCHAR(100) NOT NULL,
            org_user_id INTEGER NOT NULL REFERENCES "user"(id),
            org_type VARCHAR(20) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """),
    ("create dept_product_usage table", """
        CREATE TABLE IF NOT EXISTS dept_product_usage (
            id SERIAL PRIMARY KEY,
            department_id INTEGER NOT NULL REFERENCES department(id),
            product_id INTEGER REFERENCES product(id),
            product_name VARCHAR(200),
            quantity INTEGER NOT NULL,
            unit VARCHAR(20) DEFAULT 'unit',
            recorded_by INTEGER NOT NULL REFERENCES "user"(id),
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """),
    ("add department_id to user", """
        ALTER TABLE "user" ADD COLUMN IF NOT EXISTS department_id INTEGER REFERENCES department(id)
    """),
    ("add dept_id to order", """
        ALTER TABLE "order" ADD COLUMN IF NOT EXISTS dept_id INTEGER REFERENCES department(id)
    """),
    ("add is_dept_request to order", """
        ALTER TABLE "order" ADD COLUMN IF NOT EXISTS is_dept_request BOOLEAN DEFAULT FALSE
    """),
]

for label, sql in migrations:
    try:
        cur.execute(sql)
        conn.commit()
        print(f"OK: {label}")
    except Exception as e:
        conn.rollback()
        print(f"SKIP ({label}): {e}")

cur.close()
conn.close()
print("Department migrations complete.")
