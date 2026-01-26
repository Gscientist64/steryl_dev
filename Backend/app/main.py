# backend/app/main.py

from fastapi import FastAPI
from app.db.session import Base, engine

print("Testing DB connection...")

Base.metadata.create_all(bind=engine)
print("✅ Database connected and tables created successfully!")

app = FastAPI()
