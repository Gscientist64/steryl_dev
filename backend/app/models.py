# STERYL_UP/app/models.py
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
import re
from . import db, bcrypt

class User(db.Model, UserMixin):
    __tablename__ = 'user'

    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(120), nullable=False)
    last_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password = db.Column(db.String(256), nullable=False)
    phone = db.Column(db.String(15), nullable=True)
    country = db.Column(db.String(100), nullable=True)
    account_type = db.Column(db.String(50), nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())

    def __init__(self, first_name, last_name, email, password, phone, country, account_type):
        # Validate inputs
        if not first_name or not last_name:
            raise ValueError("First name and last name are required")
        
        if not email or not self.is_valid_email(email):
            raise ValueError("Valid email is required")
        
        if not password or len(password) < 8:
            raise ValueError("Password must be at least 8 characters")
        
        self.first_name = first_name.strip()
        self.last_name = last_name.strip()
        self.email = email.strip().lower()
        self.set_password(password)
        self.phone = phone.strip() if phone else None
        self.country = country.strip() if country else None
        self.account_type = account_type.strip()

    def set_password(self, password):
        """Hash the password using bcrypt"""
        # Use bcrypt for consistent hashing
        self.password = bcrypt.generate_password_hash(password).decode('utf-8')

    def check_password(self, password):
        """Check if the provided password matches the stored hash"""
        try:
            return bcrypt.check_password_hash(self.password, password)
        except Exception as e:
            # Fallback to werkzeug's check for older hashes
            try:
                return check_password_hash(self.password, password)
            except:
                return False

    @staticmethod
    def is_valid_email(email):
        """Validate email format"""
        pattern = r'^[^\s@]+@[^\s@]+\.[^\s@]+$'
        return re.match(pattern, email) is not None

    def to_dict(self):
        """Convert user object to dictionary for JSON serialization"""
        return {
            'id': self.id,
            'first_name': self.first_name,
            'last_name': self.last_name,
            'email': self.email,
            'phone': self.phone,
            'country': self.country,
            'account_type': self.account_type,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

    def __repr__(self):
        return f"<User {self.first_name} {self.last_name} ({self.email})>"