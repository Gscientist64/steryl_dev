# STERYL_UP/app/models.py
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
import re
from datetime import datetime, date
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
    department = db.Column(db.String(100), nullable=True)
    role = db.Column(db.String(50), default='staff')
    spend_limit = db.Column(db.Float, default=5000.00)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())
    
    # Relationships
    orders = db.relationship('Order', backref='requester', lazy=True, foreign_keys='Order.requester_id')
    approvals = db.relationship('Approval', backref='approver', lazy=True, foreign_keys='Approval.approver_id')

    def __init__(self, first_name, last_name, email, password, phone, country, account_type):
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
        self.password = bcrypt.generate_password_hash(password).decode('utf-8')

    def check_password(self, password):
        try:
            return bcrypt.check_password_hash(self.password, password)
        except:
            try:
                return check_password_hash(self.password, password)
            except:
                return False

    @staticmethod
    def is_valid_email(email):
        pattern = r'^[^\s@]+@[^\s@]+\.[^\s@]+$'
        return re.match(pattern, email) is not None

    def to_dict(self):
        return {
            'id': self.id,
            'first_name': self.first_name,
            'last_name': self.last_name,
            'email': self.email,
            'phone': self.phone,
            'country': self.country,
            'account_type': self.account_type,
            'department': self.department,
            'role': self.role,
            'spend_limit': self.spend_limit,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

    def __repr__(self):
        return f"<User {self.first_name} {self.last_name} ({self.email})>"


class Category(db.Model):
    __tablename__ = 'category'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    
    products = db.relationship('Product', backref='category', lazy=True)
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description
        }


class Product(db.Model):
    __tablename__ = 'product'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    sku = db.Column(db.String(50), unique=True, nullable=False, index=True)
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'))
    unit_price = db.Column(db.Float, nullable=False)
    unit = db.Column(db.String(20), default='unit')
    image_url = db.Column(db.String(500))
    reorder_level = db.Column(db.Integer, default=50)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())
    
    batches = db.relationship('Batch', backref='product', lazy=True)
    order_items = db.relationship('OrderItem', backref='product', lazy=True)
    
    def get_total_stock(self):
        total = sum(batch.quantity for batch in self.batches if batch.status == 'active')
        return total
    
    def get_stock_health(self):
        total = self.get_total_stock()
        if total <= self.reorder_level:
            return 'critical'
        elif total <= self.reorder_level * 1.5:
            return 'low'
        elif total >= self.reorder_level * 5:
            return 'excess'
        return 'optimal'
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'sku': self.sku,
            'category_id': self.category_id,
            'category': self.category.name if self.category else None,
            'unit_price': self.unit_price,
            'unit': self.unit,
            'image_url': self.image_url,
            'reorder_level': self.reorder_level,
            'total_stock': self.get_total_stock(),
            'stock_health': self.get_stock_health()
        }


class Batch(db.Model):
    __tablename__ = 'batch'
    
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    batch_number = db.Column(db.String(50), unique=True, nullable=False, index=True)
    quantity = db.Column(db.Integer, default=0)
    manufacturing_date = db.Column(db.Date)
    expiry_date = db.Column(db.Date)
    status = db.Column(db.String(20), default='active')
    location = db.Column(db.String(100))
    is_verified = db.Column(db.Boolean, default=False)
    qr_code = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())
    
    movements = db.relationship('StockMovement', backref='batch', lazy=True)
    scans = db.relationship('ScanHistory', backref='batch', lazy=True)
    print_queue = db.relationship('PrintQueue', backref='batch', lazy=True, uselist=False)
    
    def is_expired(self):
        return self.expiry_date and self.expiry_date < date.today()
    
    def to_dict(self):
        return {
            'id': self.id,
            'product_id': self.product_id,
            'product_name': self.product.name if self.product else None,
            'batch_number': self.batch_number,
            'quantity': self.quantity,
            'manufacturing_date': self.manufacturing_date.isoformat() if self.manufacturing_date else None,
            'expiry_date': self.expiry_date.isoformat() if self.expiry_date else None,
            'status': self.status,
            'location': self.location,
            'is_verified': self.is_verified,
            'created_at': self.created_at.isoformat()
        }


class Manufacturer(db.Model):
    __tablename__ = 'manufacturer'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    legal_entity_name = db.Column(db.String(200), nullable=False)
    medical_license_number = db.Column(db.String(100), unique=True)
    business_address = db.Column(db.Text)
    verification_status = db.Column(db.String(20), default='pending')
    documents = db.Column(db.Text)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())
    
    user = db.relationship('User', backref='manufacturer_profile')
    products = db.relationship('ProductSKU', backref='manufacturer', lazy=True)
    
    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'legal_entity_name': self.legal_entity_name,
            'medical_license_number': self.medical_license_number,
            'business_address': self.business_address,
            'verification_status': self.verification_status,
            'created_at': self.created_at.isoformat()
        }


class ProductSKU(db.Model):
    __tablename__ = 'product_sku'
    
    id = db.Column(db.Integer, primary_key=True)
    manufacturer_id = db.Column(db.Integer, db.ForeignKey('manufacturer.id'), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    sku = db.Column(db.String(50), unique=True, nullable=False, index=True)
    category = db.Column(db.String(100))
    description = db.Column(db.Text)
    unit_price = db.Column(db.Float, default=0)
    reorder_level = db.Column(db.Integer, default=50)
    status = db.Column(db.String(20), default='active')
    image_url = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())
    
    marketplace_listings = db.relationship('MarketplaceListing', backref='product_sku', lazy=True)
    
    def get_total_stock(self):
        # This would need a proper batch relationship - simplified for now
        return 0
    
    def to_dict(self):
        return {
            'id': self.id,
            'manufacturer_id': self.manufacturer_id,
            'name': self.name,
            'sku': self.sku,
            'category': self.category,
            'description': self.description,
            'unit_price': self.unit_price,
            'reorder_level': self.reorder_level,
            'status': self.status,
            'total_stock': self.get_total_stock(),
            'created_at': self.created_at.isoformat()
        }


class SupportTicket(db.Model):
    __tablename__ = 'support_ticket'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    ticket_number = db.Column(db.String(50), unique=True, nullable=False)
    subject = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(50))
    priority = db.Column(db.String(20), default='medium')
    description = db.Column(db.Text)
    status = db.Column(db.String(20), default='open')
    attachments = db.Column(db.Text)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())
    
    user = db.relationship('User', backref='support_tickets')
    
    def to_dict(self):
        return {
            'id': self.id,
            'ticket_number': self.ticket_number,
            'subject': self.subject,
            'category': self.category,
            'priority': self.priority,
            'description': self.description,
            'status': self.status,
            'created_at': self.created_at.isoformat()
        }


class PrintQueue(db.Model):
    __tablename__ = 'print_queue'
    
    id = db.Column(db.Integer, primary_key=True)
    batch_id = db.Column(db.Integer, db.ForeignKey('batch.id'), nullable=False)
    status = db.Column(db.String(20), default='pending')
    qr_pdf_url = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())
    
    def to_dict(self):
        return {
            'id': self.id,
            'batch_id': self.batch_id,
            'status': self.status,
            'qr_pdf_url': self.qr_pdf_url,
            'created_at': self.created_at.isoformat()
        }


class Transaction(db.Model):
    __tablename__ = 'transaction'
    
    id = db.Column(db.Integer, primary_key=True)
    manufacturer_id = db.Column(db.Integer, db.ForeignKey('manufacturer.id'), nullable=False)
    transaction_id = db.Column(db.String(50), unique=True, nullable=False)
    service_type = db.Column(db.String(50))
    amount = db.Column(db.Float, default=0)
    batch_volume = db.Column(db.Integer, default=0)
    status = db.Column(db.String(20), default='pending')
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    
    manufacturer = db.relationship('Manufacturer', backref='transactions')
    
    def to_dict(self):
        return {
            'id': self.id,
            'transaction_id': self.transaction_id,
            'service_type': self.service_type,
            'amount': self.amount,
            'batch_volume': self.batch_volume,
            'status': self.status,
            'created_at': self.created_at.isoformat()
        }


class MarketplaceListing(db.Model):
    __tablename__ = 'marketplace_listing'
    
    id = db.Column(db.Integer, primary_key=True)
    product_sku_id = db.Column(db.Integer, db.ForeignKey('product_sku.id'), nullable=False)
    supplier_id = db.Column(db.Integer, db.ForeignKey('manufacturer.id'), nullable=False)
    price = db.Column(db.Float, default=0)
    available_quantity = db.Column(db.Integer, default=0)
    region = db.Column(db.String(50))
    status = db.Column(db.String(20), default='active')
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())
    
    supplier = db.relationship('Manufacturer', foreign_keys=[supplier_id], backref='listings')
    
    def to_dict(self):
        return {
            'id': self.id,
            'product_sku_id': self.product_sku_id,
            'product_name': self.product_sku.name if self.product_sku else None,
            'price': self.price,
            'available_quantity': self.available_quantity,
            'region': self.region,
            'status': self.status,
            'created_at': self.created_at.isoformat()
        }


# ============ EXISTING MODELS (Keep these as they are) ============

class Order(db.Model):
    __tablename__ = 'order'
    
    id = db.Column(db.Integer, primary_key=True)
    order_number = db.Column(db.String(50), unique=True, nullable=False, index=True)
    requester_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    order_type = db.Column(db.String(20), default='purchase')
    status = db.Column(db.String(20), default='pending')
    priority = db.Column(db.String(20), default='normal')
    notes = db.Column(db.Text)
    total_amount = db.Column(db.Float, default=0.0)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())
    
    items = db.relationship('OrderItem', backref='order', lazy=True, cascade='all, delete-orphan')
    approvals = db.relationship('Approval', backref='order', lazy=True)
    
    def calculate_total(self):
        self.total_amount = sum(item.quantity * item.unit_price for item in self.items)
        return self.total_amount
    
    def to_dict(self):
        return {
            'id': self.id,
            'order_number': self.order_number,
            'requester_id': self.requester_id,
            'requester_name': f"{self.requester.first_name} {self.requester.last_name}" if self.requester else None,
            'order_type': self.order_type,
            'status': self.status,
            'priority': self.priority,
            'notes': self.notes,
            'total_amount': self.total_amount,
            'items': [item.to_dict() for item in self.items],
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }


class OrderItem(db.Model):
    __tablename__ = 'order_item'
    
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    unit_price = db.Column(db.Float, nullable=False)
    subtotal = db.Column(db.Float)
    
    def calculate_subtotal(self):
        self.subtotal = self.quantity * self.unit_price
        return self.subtotal
    
    def to_dict(self):
        return {
            'id': self.id,
            'product_id': self.product_id,
            'product_name': self.product.name if self.product else None,
            'quantity': self.quantity,
            'unit_price': self.unit_price,
            'subtotal': self.calculate_subtotal()
        }


class Approval(db.Model):
    __tablename__ = 'approval'
    
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=False)
    approver_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    status = db.Column(db.String(20), default='pending')
    comments = db.Column(db.Text)
    approved_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    
    def to_dict(self):
        return {
            'id': self.id,
            'order_id': self.order_id,
            'approver_id': self.approver_id,
            'approver_name': f"{self.approver.first_name} {self.approver.last_name}" if self.approver else None,
            'status': self.status,
            'comments': self.comments,
            'approved_at': self.approved_at.isoformat() if self.approved_at else None,
            'created_at': self.created_at.isoformat()
        }


class StockMovement(db.Model):
    __tablename__ = 'stock_movement'
    
    id = db.Column(db.Integer, primary_key=True)
    batch_id = db.Column(db.Integer, db.ForeignKey('batch.id'), nullable=False)
    movement_type = db.Column(db.String(20), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    from_location = db.Column(db.String(100))
    to_location = db.Column(db.String(100))
    reference_id = db.Column(db.String(100))
    notes = db.Column(db.Text)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    
    user = db.relationship('User', backref='movements')
    
    def to_dict(self):
        return {
            'id': self.id,
            'batch_id': self.batch_id,
            'batch_number': self.batch.batch_number if self.batch else None,
            'movement_type': self.movement_type,
            'quantity': self.quantity,
            'from_location': self.from_location,
            'to_location': self.to_location,
            'reference_id': self.reference_id,
            'notes': self.notes,
            'user_id': self.user_id,
            'user_name': f"{self.user.first_name} {self.user.last_name}" if self.user else None,
            'created_at': self.created_at.isoformat()
        }


class SyncConflict(db.Model):
    __tablename__ = 'sync_conflict'
    
    id = db.Column(db.Integer, primary_key=True)
    entity_type = db.Column(db.String(50), nullable=False)
    entity_id = db.Column(db.Integer, nullable=False)
    local_data = db.Column(db.Text)
    server_data = db.Column(db.Text)
    resolved = db.Column(db.Boolean, default=False)
    resolved_at = db.Column(db.DateTime)
    resolved_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    
    def to_dict(self):
        return {
            'id': self.id,
            'entity_type': self.entity_type,
            'entity_id': self.entity_id,
            'local_data': self.local_data,
            'server_data': self.server_data,
            'resolved': self.resolved,
            'resolved_at': self.resolved_at.isoformat() if self.resolved_at else None,
            'created_at': self.created_at.isoformat()
        }


class ScanHistory(db.Model):
    __tablename__ = 'scan_history'
    
    id = db.Column(db.Integer, primary_key=True)
    batch_id = db.Column(db.Integer, db.ForeignKey('batch.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    scan_location = db.Column(db.String(200))
    status = db.Column(db.String(50), default='authentic')
    scan_time = db.Column(db.DateTime, server_default=db.func.now())
    notes = db.Column(db.Text)
    
    user = db.relationship('User', backref='scans')
    
    def to_dict(self):
        return {
            'id': self.id,
            'batch': self.batch.to_dict() if self.batch else None,
            'user_name': f"{self.user.first_name} {self.user.last_name}" if self.user else None,
            'scan_location': self.scan_location,
            'status': self.status,
            'scan_time': self.scan_time.isoformat(),
            'notes': self.notes
        }


class SyncQueue(db.Model):
    __tablename__ = 'sync_queue'
    
    id = db.Column(db.Integer, primary_key=True)
    action_type = db.Column(db.String(50), nullable=False)
    entity_type = db.Column(db.String(50))
    entity_id = db.Column(db.Integer)
    payload = db.Column(db.Text)
    description = db.Column(db.Text)
    status = db.Column(db.String(20), default='pending')
    error_message = db.Column(db.Text)
    retry_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())
    
    def to_dict(self):
        return {
            'id': self.id,
            'action_type': self.action_type,
            'entity_type': self.entity_type,
            'entity_id': self.entity_id,
            'payload': self.payload,
            'description': self.description,
            'status': self.status,
            'error_message': self.error_message,
            'retry_count': self.retry_count,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }


class Shipment(db.Model):
    __tablename__ = 'shipment'
    
    id = db.Column(db.Integer, primary_key=True)
    shipment_number = db.Column(db.String(50), unique=True, nullable=False, index=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'))
    supplier = db.Column(db.String(200), nullable=False)
    carrier = db.Column(db.String(100))
    tracking_number = db.Column(db.String(100))
    expected_date = db.Column(db.Date)
    received_date = db.Column(db.Date)
    status = db.Column(db.String(50), default='pending')
    intake_progress = db.Column(db.Float, default=0.0)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())
    
    items = db.relationship('ShipmentItem', backref='shipment', lazy=True, cascade='all, delete-orphan')
    order = db.relationship('Order', backref='shipments')
    
    def calculate_progress(self):
        if self.items:
            received = sum(1 for item in self.items if item.received_quantity > 0)
            self.intake_progress = (received / len(self.items)) * 100
        return self.intake_progress
    
    def to_dict(self):
        return {
            'id': self.id,
            'shipment_number': self.shipment_number,
            'order_id': self.order_id,
            'order_number': self.order.order_number if self.order else None,
            'supplier': self.supplier,
            'carrier': self.carrier,
            'tracking_number': self.tracking_number,
            'expected_date': self.expected_date.isoformat() if self.expected_date else None,
            'received_date': self.received_date.isoformat() if self.received_date else None,
            'status': self.status,
            'intake_progress': self.intake_progress,
            'items': [item.to_dict() for item in self.items],
            'created_at': self.created_at.isoformat()
        }


class ShipmentItem(db.Model):
    __tablename__ = 'shipment_item'
    
    id = db.Column(db.Integer, primary_key=True)
    shipment_id = db.Column(db.Integer, db.ForeignKey('shipment.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    batch_number = db.Column(db.String(50))
    manufacturer = db.Column(db.String(200))
    expected_quantity = db.Column(db.Integer, nullable=False)
    received_quantity = db.Column(db.Integer, default=0)
    status = db.Column(db.String(20), default='pending')
    notes = db.Column(db.Text)
    
    product = db.relationship('Product', backref='shipment_items')
    
    def to_dict(self):
        return {
            'id': self.id,
            'shipment_id': self.shipment_id,
            'product_id': self.product_id,
            'product_name': self.product.name if self.product else None,
            'product_sku': self.product.sku if self.product else None,
            'batch_number': self.batch_number,
            'manufacturer': self.manufacturer,
            'expected_quantity': self.expected_quantity,
            'received_quantity': self.received_quantity,
            'status': self.status,
            'notes': self.notes
        }


class BudgetCategory(db.Model):
    __tablename__ = 'budget_category'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    allocated = db.Column(db.Float, default=0.0)
    spent = db.Column(db.Float, default=0.0)
    month = db.Column(db.Integer)
    year = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    
    @property
    def remaining(self):
        return self.allocated - self.spent
    
    @property
    def percentage_used(self):
        if self.allocated > 0:
            return (self.spent / self.allocated) * 100
        return 0
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'allocated': self.allocated,
            'spent': self.spent,
            'remaining': self.remaining,
            'percentage_used': self.percentage_used,
            'month': self.month,
            'year': self.year
        }


class UserSettings(db.Model):
    __tablename__ = 'user_settings'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), unique=True, nullable=False)
    theme = db.Column(db.String(20), default='light')
    primary_color = db.Column(db.String(20), default='teal')
    font_size = db.Column(db.String(10), default='medium')
    reduced_motion = db.Column(db.Boolean, default=False)
    email_notifications = db.Column(db.Boolean, default=True)
    push_notifications = db.Column(db.Boolean, default=True)
    low_stock_alerts = db.Column(db.Boolean, default=True)
    order_updates = db.Column(db.Boolean, default=True)
    approval_reminders = db.Column(db.Boolean, default=True)
    compact_view = db.Column(db.Boolean, default=False)
    show_dashboard_widgets = db.Column(db.Boolean, default=True)
    default_dashboard_view = db.Column(db.String(20), default='grid')
    share_analytics = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())
    
    user = db.relationship('User', backref='settings')
    
    def to_dict(self):
        return {
            'theme': self.theme,
            'primary_color': self.primary_color,
            'font_size': self.font_size,
            'reduced_motion': self.reduced_motion,
            'email_notifications': self.email_notifications,
            'push_notifications': self.push_notifications,
            'low_stock_alerts': self.low_stock_alerts,
            'order_updates': self.order_updates,
            'approval_reminders': self.approval_reminders,
            'compact_view': self.compact_view,
            'show_dashboard_widgets': self.show_dashboard_widgets,
            'default_dashboard_view': self.default_dashboard_view,
            'share_analytics': self.share_analytics
        }


class AccountUpgradeRequest(db.Model):
    __tablename__ = 'account_upgrade_request'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    requested_account_type = db.Column(db.String(50), nullable=False)
    current_account_type = db.Column(db.String(50), nullable=False)
    reason = db.Column(db.Text)
    status = db.Column(db.String(20), default='pending')
    reviewed_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    reviewed_at = db.Column(db.DateTime)
    rejection_reason = db.Column(db.Text)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())
    
    user = db.relationship('User', foreign_keys=[user_id], backref='upgrade_requests')
    reviewer = db.relationship('User', foreign_keys=[reviewed_by])
    
    def to_dict(self):
        return {
            'id': self.id,
            'requested_account_type': self.requested_account_type,
            'current_account_type': self.current_account_type,
            'reason': self.reason,
            'status': self.status,
            'rejection_reason': self.rejection_reason,
            'created_at': self.created_at.isoformat(),
            'reviewed_at': self.reviewed_at.isoformat() if self.reviewed_at else None
        }