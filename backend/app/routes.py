# STERYL_UP/app/routes.py
from flask import render_template, redirect, url_for, flash, request, jsonify, Blueprint, current_app, session
from flask_login import login_user, login_required, logout_user, current_user
from . import db, bcrypt
from .models import (
    User, Product, Batch, Order, OrderItem, Approval, StockMovement, Category,
    Manufacturer, ProductSKU, SupportTicket, PrintQueue, Transaction, MarketplaceListing,
    UserSettings, AccountUpgradeRequest
)
from app.utils.response import APIResponse
from app.utils.validators import UserLoginSchema, UserRegisterSchema, validate_with_schema
from werkzeug.security import check_password_hash
from datetime import datetime, timedelta
from sqlalchemy import func, desc
import json
import re

bp = Blueprint('main', __name__)

# ============ PAGE ROUTES ============

@bp.route('/')
@bp.route('/index')
def index():
    return render_template('index.html')

@bp.route('/login', methods=['GET', 'POST'])
def login():
    """Handle user login with validation"""
    if request.method == 'GET':
        return render_template('login.html')
    
    elif request.method == 'POST':
        try:
            data = request.get_json()
            if not data:
                return APIResponse.error("Invalid request format", 400)
            
            is_valid, validated_data, errors = validate_with_schema(UserLoginSchema(), data)
            
            if not is_valid:
                current_app.logger.warning(f"Login validation failed for IP: {request.remote_addr}")
                return APIResponse.validation_error(errors)
            
            user = User.query.filter_by(email=validated_data['email'].lower()).first()
            
            if user:
                password_valid = False
                try:
                    password_valid = bcrypt.check_password_hash(user.password, validated_data['password'])
                except Exception as e:
                    current_app.logger.warning(f"Bcrypt check failed: {e}")
                    try:
                        password_valid = check_password_hash(user.password, validated_data['password'])
                    except Exception as e2:
                        current_app.logger.error(f"Both password checks failed: {e2}")
                        password_valid = False
                
                if password_valid:
                    login_user(user, remember=validated_data['remember'])
                    current_app.logger.info(f"User {user.email} logged in successfully")
                    
                    return APIResponse.success(
                        data={'user': user.to_dict()},
                        message="Login successful",
                        meta={'redirect': url_for('main.dashboard')}
                    )
            
            current_app.logger.warning(f"Failed login attempt for email: {validated_data['email']}")
            return APIResponse.unauthorized("Invalid email or password")
                
        except Exception as e:
            current_app.logger.error(f"Login error: {str(e)}", exc_info=True)
            return APIResponse.server_error("An error occurred during login")

@bp.route('/register', methods=['GET', 'POST'])
def register():
    """Handle user registration with validation"""
    if request.method == 'GET':
        return render_template('register.html')
    
    elif request.method == 'POST':
        try:
            data = request.get_json()
            if not data:
                return APIResponse.error("Invalid request format", 400)
            
            is_valid, validated_data, errors = validate_with_schema(UserRegisterSchema(), data)
            
            if not is_valid:
                current_app.logger.warning(f"Registration validation failed: {errors}")
                return APIResponse.validation_error(errors)
            
            existing_user = User.query.filter_by(email=validated_data['email']).first()
            if existing_user:
                return APIResponse.conflict("Email already registered. Please login instead.")
            
            new_user = User(
                first_name=validated_data['first_name'],
                last_name=validated_data['last_name'],
                email=validated_data['email'],
                password=validated_data['password'],
                phone=validated_data.get('phone'),
                country=validated_data['country'],
                account_type=validated_data['account_type']
            )
            
            db.session.add(new_user)
            db.session.commit()
            
            current_app.logger.info(f"New user registered: {new_user.email}")
            login_user(new_user)
            
            return APIResponse.success(
                data={'user': new_user.to_dict()},
                message="Account created successfully",
                status_code=201,
                meta={'redirect': url_for('main.dashboard')}
            )
            
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Registration error: {str(e)}", exc_info=True)
            return APIResponse.server_error("An error occurred during registration")

@bp.route('/logout')
@login_required
def logout():
    """Handle user logout"""
    logout_user()
    flash('You have been logged out successfully.', 'info')
    return redirect(url_for('main.login'))

# ============ STATIC PAGE ROUTES ============

@bp.route('/about')
def about():
    return render_template('about.html')

@bp.route('/solutions')
def solutions():
    return render_template('solutions.html')

@bp.route('/how-it-works')
def how_it_works():
    return render_template('how-it-works.html')

# ============ DASHBOARD ROUTES ============

@bp.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard/procurement.html')

@bp.route('/approvals')
@login_required
def approvals():
    return render_template('dashboard/approvals.html')

@bp.route('/order-cart')
@login_required
def order_cart():
    return render_template('dashboard/order-cart.html')

@bp.route('/profile')
@login_required
def profile():
    return render_template('dashboard/profile.html')

@bp.route('/budget')
@login_required
def budget():
    return render_template('dashboard/budget.html')

@bp.route('/sync-queue')
@login_required
def sync_queue():
    return render_template('dashboard/sync-queue.html')

@bp.route('/scan-history')
@login_required
def scan_history():
    return render_template('dashboard/scan-history.html')

@bp.route('/shipment-intake')
@login_required
def shipment_intake():
    return render_template('dashboard/shipment-intake.html')

@bp.route('/qr-scanner')
@login_required
def qr_scanner():
    return render_template('dashboard/qr-scanner.html')

@bp.route('/settings')
@login_required
def settings():
    """User settings page"""
    return render_template('dashboard/settings.html')

# ============ MANUFACTURER PAGE ROUTES ============

@bp.route('/manufacturer/login', methods=['GET', 'POST'])
def manufacturer_login_page():
    """Manufacturer login page"""
    if request.method == 'GET':
        return render_template('manufacturer/login.html')
    
    elif request.method == 'POST':
        try:
            data = request.get_json()
            email = data.get('email')
            password = data.get('password')
            
            user = User.query.filter_by(email=email).first()
            
            if user and bcrypt.check_password_hash(user.password, password):
                login_user(user)
                
                # Ensure manufacturer profile exists
                manufacturer = Manufacturer.query.filter_by(user_id=user.id).first()
                if not manufacturer and user.account_type == 'manufacturer':
                    manufacturer = Manufacturer(
                        user_id=user.id,
                        legal_entity_name=user.first_name + ' ' + user.last_name,
                        verification_status='pending'
                    )
                    db.session.add(manufacturer)
                    db.session.commit()
                
                return APIResponse.success(
                    message="Login successful",
                    meta={'redirect': url_for('main.manufacturer_skus')}
                )
            else:
                return APIResponse.error("Invalid email or password", 401)
        except Exception as e:
            current_app.logger.error(f"Manufacturer login error: {str(e)}")
            return APIResponse.server_error(str(e))

@bp.route('/manufacturer/register', methods=['POST'])
def manufacturer_register_api():
    """Manufacturer registration API"""
    try:
        data = request.get_json()
        
        if data.get('password') != data.get('confirm_password'):
            return APIResponse.error("Passwords do not match", 400)
        
        existing_user = User.query.filter_by(email=data.get('email')).first()
        if existing_user:
            return APIResponse.error("Email already registered", 409)
        
        hashed_password = bcrypt.generate_password_hash(data.get('password')).decode('utf-8')
        
        user = User(
            first_name=data.get('company_name').split()[0] if data.get('company_name') else 'Manufacturer',
            last_name='',
            email=data.get('email'),
            password=hashed_password,
            phone=data.get('phone', ''),
            country='',
            account_type='manufacturer'
        )
        db.session.add(user)
        db.session.flush()
        
        manufacturer = Manufacturer(
            user_id=user.id,
            legal_entity_name=data.get('company_name'),
            medical_license_number=data.get('license_number'),
            verification_status='pending'
        )
        db.session.add(manufacturer)
        db.session.commit()
        
        login_user(user)
        return APIResponse.success(
            message="Registration successful!",
            meta={'redirect': url_for('main.manufacturer_skus')}
        )
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Manufacturer registration error: {str(e)}")
        return APIResponse.server_error(str(e))

@bp.route('/manufacturer/skus')
@login_required
def manufacturer_skus():
    """Manufacturer SKU inventory page"""
    return render_template('manufacturer/sku-inventory.html')

@bp.route('/manufacturer/batches')
@login_required
def manufacturer_batches():
    """Manufacturer batch dashboard"""
    return render_template('manufacturer/batch-dashboard.html')

@bp.route('/manufacturer/batch/register')
@login_required
def manufacturer_batch_register():
    """Batch registration page"""
    return render_template('manufacturer/batch-registration.html')

@bp.route('/manufacturer/print-queue')
@login_required
def manufacturer_print_queue():
    """Print queue page"""
    return render_template('manufacturer/print-queue.html')

@bp.route('/manufacturer/label/preview')
@login_required
def manufacturer_label_preview():
    """Label preview page"""
    return render_template('manufacturer/verified-label-preview.html')

# ============ SUPPORT ROUTES ============

@bp.route('/support/new')
@login_required
def support_new_ticket():
    """Submit new support ticket"""
    return render_template('support/new-ticket.html')

@bp.route('/support/tickets')
@login_required
def support_tickets():
    """View all support tickets"""
    return render_template('support/tickets.html')

# ============ API ROUTES ============

@bp.route('/api/user-profile')
@login_required
def api_user_profile():
    """Get current user profile data"""
    try:
        return APIResponse.success(
            data={
                'id': current_user.id,
                'first_name': current_user.first_name,
                'last_name': current_user.last_name,
                'email': current_user.email,
                'phone': current_user.phone,
                'country': current_user.country,
                'department': current_user.department,
                'role': current_user.role,
                'spend_limit': current_user.spend_limit or 50000,
                'account_type': current_user.account_type
            },
            message="Profile retrieved"
        )
    except Exception as e:
        current_app.logger.error(f"User profile error: {str(e)}")
        return APIResponse.server_error(str(e))

# ============ MANUFACTURER API ROUTES ============

@bp.route('/api/manufacturer/skus')
@login_required
def api_manufacturer_skus():
    """Get all SKUs for the current manufacturer"""
    try:
        manufacturer = Manufacturer.query.filter_by(user_id=current_user.id).first()
        if not manufacturer:
            return APIResponse.success(data=[], message="No manufacturer profile found")
        
        products = ProductSKU.query.filter_by(manufacturer_id=manufacturer.id).all()
        return APIResponse.success(
            data=[p.to_dict() for p in products],
            message="SKUs retrieved"
        )
    except Exception as e:
        current_app.logger.error(f"SKU API error: {str(e)}")
        return APIResponse.success(data=[], message="No products found")

@bp.route('/api/manufacturer/stats')
@login_required
def api_manufacturer_stats():
    """Get manufacturer statistics"""
    try:
        manufacturer = Manufacturer.query.filter_by(user_id=current_user.id).first()
        if not manufacturer:
            return APIResponse.success(data={
                'total_skus': 0,
                'active_skus': 0,
                'pending_skus': 0,
                'total_batches': 0,
                'total_units': 0
            }, message="No manufacturer profile")
        
        products = ProductSKU.query.filter_by(manufacturer_id=manufacturer.id).all()
        product_ids = [p.id for p in products]
        batches = Batch.query.filter(Batch.product_id.in_(product_ids)).all() if product_ids else []
        
        total_skus = len(products)
        active_skus = len([p for p in products if p.status == 'active'])
        pending_skus = len([p for p in products if p.status == 'pending'])
        total_batches = len(batches)
        total_units = sum(b.quantity for b in batches)
        
        return APIResponse.success(data={
            'total_skus': total_skus,
            'active_skus': active_skus,
            'pending_skus': pending_skus,
            'total_batches': total_batches,
            'total_units': total_units
        }, message="Stats retrieved")
    except Exception as e:
        current_app.logger.error(f"Stats error: {str(e)}")
        return APIResponse.server_error(str(e))

@bp.route('/api/manufacturer/batches')
@login_required
def api_manufacturer_batches():
    """Get all batches for the manufacturer"""
    try:
        manufacturer = Manufacturer.query.filter_by(user_id=current_user.id).first()
        if not manufacturer:
            return APIResponse.success(data=[], message="No manufacturer profile")
        
        product_ids = [p.id for p in ProductSKU.query.filter_by(manufacturer_id=manufacturer.id).all()]
        batches = Batch.query.filter(Batch.product_id.in_(product_ids)).order_by(Batch.created_at.desc()).all() if product_ids else []
        
        return APIResponse.success(
            data=[b.to_dict() for b in batches],
            message="Batches retrieved"
        )
    except Exception as e:
        current_app.logger.error(f"Batches API error: {str(e)}")
        return APIResponse.success(data=[], message="No batches found")

@bp.route('/api/manufacturer/batch/register', methods=['POST'])
@login_required
def api_manufacturer_batch_register():
    """Register a new batch"""
    try:
        data = request.get_json()
        
        manufacturer = Manufacturer.query.filter_by(user_id=current_user.id).first()
        if not manufacturer:
            return APIResponse.error("Manufacturer profile not found", 400)
        
        product = ProductSKU.query.get(data.get('product_id'))
        if not product:
            return APIResponse.error("Product not found", 404)
        
        batch_number = f"BATCH-{datetime.now().strftime('%Y%m%d')}-{Batch.query.count() + 1}"
        qr_code = f"https://steryl.com/verify/{batch_number}"
        
        batch = Batch(
            product_id=product.id,
            batch_number=batch_number,
            quantity=data.get('quantity', 0),
            manufacturing_date=datetime.strptime(data.get('manufacturing_date'), '%Y-%m-%d').date() if data.get('manufacturing_date') else None,
            expiry_date=datetime.strptime(data.get('expiry_date'), '%Y-%m-%d').date() if data.get('expiry_date') else None,
            status='active',
            is_verified=True,
            qr_code=qr_code
        )
        db.session.add(batch)
        db.session.commit()
        
        print_item = PrintQueue(batch_id=batch.id, status='pending')
        db.session.add(print_item)
        db.session.commit()
        
        return APIResponse.success(
            data=batch.to_dict(),
            message="Batch registered successfully",
            status_code=201
        )
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Batch registration error: {str(e)}")
        return APIResponse.server_error(str(e))

# ============ PRINT QUEUE API ROUTES ============

@bp.route('/api/print-queue')
@login_required
def api_print_queue():
    """Get print queue for manufacturer"""
    try:
        manufacturer = Manufacturer.query.filter_by(user_id=current_user.id).first()
        if not manufacturer:
            return APIResponse.success(data=[], message="No manufacturer profile")
        
        product_ids = [p.id for p in ProductSKU.query.filter_by(manufacturer_id=manufacturer.id).all()]
        batches = Batch.query.filter(Batch.product_id.in_(product_ids)).order_by(Batch.created_at.desc()).all() if product_ids else []
        
        queue_items = []
        for batch in batches:
            print_item = PrintQueue.query.filter_by(batch_id=batch.id).first()
            if print_item:
                queue_items.append({
                    'id': print_item.id,
                    'batch_id': batch.id,
                    'batch_number': batch.batch_number,
                    'product_name': batch.product.name if batch.product else None,
                    'quantity': batch.quantity,
                    'status': print_item.status,
                    'created_at': batch.created_at.isoformat()
                })
            else:
                new_print = PrintQueue(batch_id=batch.id, status='pending')
                db.session.add(new_print)
                db.session.commit()
                queue_items.append({
                    'id': new_print.id,
                    'batch_id': batch.id,
                    'batch_number': batch.batch_number,
                    'product_name': batch.product.name if batch.product else None,
                    'quantity': batch.quantity,
                    'status': 'pending',
                    'created_at': batch.created_at.isoformat()
                })
        
        return APIResponse.success(data=queue_items, message="Print queue retrieved")
    except Exception as e:
        current_app.logger.error(f"Print queue error: {str(e)}")
        return APIResponse.server_error(str(e))

@bp.route('/api/print-queue/<int:queue_id>/download', methods=['POST'])
@login_required
def api_print_queue_download(queue_id):
    """Download QR label PDF"""
    try:
        print_item = PrintQueue.query.get_or_404(queue_id)
        batch = Batch.query.get(print_item.batch_id)
        
        print_item.status = 'ready'
        db.session.commit()
        
        return APIResponse.success(
            data={
                'batch_number': batch.batch_number,
                'qr_code': batch.qr_code,
                'download_url': f"/static/labels/{batch.batch_number}.pdf"
            },
            message="Label ready for download"
        )
    except Exception as e:
        current_app.logger.error(f"Download label error: {str(e)}")
        return APIResponse.server_error(str(e))

@bp.route('/api/print-queue/<int:queue_id>/printed', methods=['POST'])
@login_required
def api_print_queue_mark_printed(queue_id):
    """Mark label as printed"""
    try:
        print_item = PrintQueue.query.get_or_404(queue_id)
        print_item.status = 'printed'
        db.session.commit()
        
        return APIResponse.success(message="Label marked as printed")
    except Exception as e:
        current_app.logger.error(f"Mark printed error: {str(e)}")
        return APIResponse.server_error(str(e))

@bp.route('/api/print-queue/print-all', methods=['POST'])
@login_required
def api_print_queue_print_all():
    """Print all pending labels"""
    try:
        pending_items = PrintQueue.query.filter_by(status='pending').all()
        for item in pending_items:
            item.status = 'ready'
        db.session.commit()
        
        return APIResponse.success(
            data={'count': len(pending_items)},
            message=f"{len(pending_items)} labels queued for printing"
        )
    except Exception as e:
        current_app.logger.error(f"Print all error: {str(e)}")
        return APIResponse.server_error(str(e))

# ============ SUPPORT TICKET API ROUTES ============

@bp.route('/api/support/tickets')
@login_required
def api_support_tickets():
    """Get user's support tickets"""
    try:
        tickets = SupportTicket.query.filter_by(user_id=current_user.id).order_by(desc(SupportTicket.created_at)).all()
        
        return APIResponse.success(
            data=[t.to_dict() for t in tickets],
            message="Tickets retrieved"
        )
    except Exception as e:
        current_app.logger.error(f"Tickets error: {str(e)}")
        return APIResponse.success(data=[], message="No tickets found")

@bp.route('/api/support/tickets/new', methods=['POST'])
@login_required
def api_support_tickets_new():
    """Create new support ticket"""
    try:
        data = request.get_json()
        
        ticket_number = f"SR-{datetime.now().strftime('%Y%m%d')}-{SupportTicket.query.count() + 1}"
        
        ticket = SupportTicket(
            user_id=current_user.id,
            ticket_number=ticket_number,
            subject=data.get('subject'),
            category=data.get('category'),
            priority=data.get('priority', 'medium'),
            description=data.get('description'),
            status='open'
        )
        db.session.add(ticket)
        db.session.commit()
        
        return APIResponse.success(
            data=ticket.to_dict(),
            message="Ticket created successfully",
            status_code=201
        )
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"New ticket error: {str(e)}")
        return APIResponse.server_error(str(e))

# ============ DASHBOARD API ROUTES ============

@bp.route('/api/dashboard-stats')
@login_required
def api_dashboard_stats():
    """Get dashboard statistics"""
    try:
        products = Product.query.all()
        total_products = len(products)
        low_stock_count = sum(1 for p in products if p.get_total_stock() <= p.reorder_level)
        inventory_health = ((total_products - low_stock_count) / total_products * 100) if total_products > 0 else 100
        
        pending_orders = Order.query.filter_by(status='pending').count()
        active_orders = Order.query.filter(Order.status.in_(['pending', 'approved'])).count()
        
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        monthly_spend = db.session.query(func.sum(Order.total_amount)).filter(
            Order.created_at >= thirty_days_ago,
            Order.status == 'approved'
        ).scalar() or 0
        
        return APIResponse.success(
            data={
                'inventory_health': round(inventory_health, 1),
                'pending_approvals': pending_orders,
                'monthly_spend': float(monthly_spend),
                'active_orders': active_orders,
                'inventory_health_change': 2.4
            },
            message="Dashboard stats retrieved"
        )
    except Exception as e:
        current_app.logger.error(f"Dashboard stats error: {str(e)}")
        return APIResponse.server_error(str(e))

@bp.route('/api/stock-alerts')
@login_required
def api_stock_alerts():
    """Get products with low stock levels"""
    try:
        products = Product.query.all()
        alerts = []
        
        for product in products:
            stock = product.get_total_stock()
            if stock <= product.reorder_level:
                alerts.append({
                    'product': product.to_dict(),
                    'current_stock': stock,
                    'reorder_level': product.reorder_level,
                    'deficit': product.reorder_level - stock,
                    'severity': 'critical' if stock <= product.reorder_level / 2 else 'warning'
                })
        
        return APIResponse.success(data=alerts, message="Stock alerts retrieved")
    except Exception as e:
        current_app.logger.error(f"Stock alerts error: {str(e)}")
        return APIResponse.server_error(str(e))

@bp.route('/api/approvals')
@login_required
def api_approvals():
    """Get all approvals"""
    try:
        all_orders = Order.query.order_by(desc(Order.created_at)).all()
        
        approval_data = []
        for order in all_orders:
            sla_remaining = None
            if order.status == 'pending':
                time_created = order.created_at
                time_remaining = (time_created + timedelta(hours=24)) - datetime.utcnow()
                hours_remaining = max(0, time_remaining.total_seconds() / 3600)
                sla_remaining = {
                    'hours': round(hours_remaining, 1),
                    'text': f"{int(hours_remaining)}h {int((hours_remaining % 1) * 60)}m" if hours_remaining > 1 else f"{int(hours_remaining * 60)}m"
                }
            
            approval_data.append({
                'order': order.to_dict(),
                'sla_remaining_hours': sla_remaining['hours'] if sla_remaining else None,
                'sla_remaining_text': sla_remaining['text'] if sla_remaining else None
            })
        
        return APIResponse.success(data=approval_data, message="Approvals retrieved")
    except Exception as e:
        current_app.logger.error(f"Approvals API error: {str(e)}")
        return APIResponse.success(data=[], message="No approvals found")

@bp.route('/api/approvals/<int:order_id>/<action>', methods=['POST'])
@login_required
def api_process_approval(order_id, action):
    """Approve or reject an order"""
    try:
        if action not in ['approve', 'reject']:
            return APIResponse.error("Invalid action", 400)
        
        order = Order.query.get_or_404(order_id)
        
        if action == 'approve':
            order.status = 'approved'
            message = f"Order #{order.order_number} approved successfully"
        else:
            order.status = 'rejected'
            message = f"Order #{order.order_number} rejected"
        
        order.updated_at = datetime.utcnow()
        
        approval = Approval(
            order_id=order.id,
            approver_id=current_user.id,
            status=action,
            comments=request.json.get('comments', ''),
            approved_at=datetime.utcnow()
        )
        db.session.add(approval)
        db.session.commit()
        
        return APIResponse.success(
            data={'order_id': order.id, 'status': order.status},
            message=message
        )
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Process approval error: {str(e)}")
        return APIResponse.server_error(str(e))

@bp.route('/api/products')
@login_required
def api_products():
    """Get all products with stock levels"""
    try:
        products = Product.query.all()
        return APIResponse.success(
            data=[p.to_dict() for p in products],
            message="Products retrieved successfully"
        )
    except Exception as e:
        current_app.logger.error(f"Products API error: {str(e)}")
        return APIResponse.server_error(str(e))

@bp.route('/api/orders', methods=['GET', 'POST'])
@login_required
def api_orders():
    """Get all orders or create new order"""
    try:
        if request.method == 'GET':
            orders = Order.query.filter_by(requester_id=current_user.id).order_by(desc(Order.created_at)).all()
            return APIResponse.success(
                data=[o.to_dict() for o in orders],
                message="Orders retrieved"
            )
        
        elif request.method == 'POST':
            data = request.get_json()
            
            order_number = f"ORD-{datetime.now().strftime('%Y%m%d%H%M%S')}"
            
            order = Order(
                order_number=order_number,
                requester_id=current_user.id,
                order_type=data.get('order_type', 'purchase'),
                priority=data.get('priority', 'normal'),
                notes=data.get('notes', '')
            )
            db.session.add(order)
            db.session.flush()
            
            total = 0
            for item_data in data.get('items', []):
                product = Product.query.get(item_data['product_id'])
                if not product:
                    continue
                    
                item = OrderItem(
                    order_id=order.id,
                    product_id=product.id,
                    quantity=item_data['quantity'],
                    unit_price=product.unit_price
                )
                item.calculate_subtotal()
                total += item.subtotal
                db.session.add(item)
            
            order.total_amount = total
            db.session.commit()
            
            return APIResponse.success(
                data=order.to_dict(),
                message="Order created successfully",
                status_code=201
            )
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Order API error: {str(e)}")
        return APIResponse.server_error(str(e))

# ============ SETTINGS API ROUTES ============

@bp.route('/api/user-settings', methods=['GET', 'PUT'])
@login_required
def api_user_settings():
    """Get or update user settings"""
    try:
        settings = UserSettings.query.filter_by(user_id=current_user.id).first()
        if not settings:
            settings = UserSettings(user_id=current_user.id)
            db.session.add(settings)
            db.session.commit()
        
        if request.method == 'GET':
            return APIResponse.success(
                data=settings.to_dict(),
                message="Settings retrieved"
            )
        
        elif request.method == 'PUT':
            data = request.get_json()
            
            if 'theme' in data:
                settings.theme = data['theme']
            if 'primary_color' in data:
                settings.primary_color = data['primary_color']
            if 'font_size' in data:
                settings.font_size = data['font_size']
            if 'reduced_motion' in data:
                settings.reduced_motion = data['reduced_motion']
            if 'email_notifications' in data:
                settings.email_notifications = data['email_notifications']
            if 'push_notifications' in data:
                settings.push_notifications = data['push_notifications']
            if 'low_stock_alerts' in data:
                settings.low_stock_alerts = data['low_stock_alerts']
            if 'order_updates' in data:
                settings.order_updates = data['order_updates']
            if 'approval_reminders' in data:
                settings.approval_reminders = data['approval_reminders']
            if 'compact_view' in data:
                settings.compact_view = data['compact_view']
            if 'show_dashboard_widgets' in data:
                settings.show_dashboard_widgets = data['show_dashboard_widgets']
            if 'default_dashboard_view' in data:
                settings.default_dashboard_view = data['default_dashboard_view']
            if 'share_analytics' in data:
                settings.share_analytics = data['share_analytics']
            
            settings.updated_at = datetime.utcnow()
            db.session.commit()
            
            return APIResponse.success(
                data=settings.to_dict(),
                message="Settings updated successfully"
            )
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Settings API error: {str(e)}")
        return APIResponse.server_error(str(e))

@bp.route('/api/update-profile', methods=['PUT'])
@login_required
def api_update_profile():
    """Update user profile information"""
    try:
        data = request.get_json()
        
        if 'first_name' in data and data['first_name']:
            current_user.first_name = data['first_name']
        if 'last_name' in data and data['last_name']:
            current_user.last_name = data['last_name']
        if 'phone' in data:
            current_user.phone = data['phone']
        if 'department' in data:
            current_user.department = data['department']
        
        db.session.commit()
        
        return APIResponse.success(
            data=current_user.to_dict(),
            message="Profile updated successfully"
        )
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Update profile error: {str(e)}")
        return APIResponse.server_error(str(e))

@bp.route('/api/request-upgrade', methods=['POST'])
@login_required
def api_request_upgrade():
    """Request account type upgrade"""
    try:
        data = request.get_json()
        requested_type = data.get('account_type')
        reason = data.get('reason', '')
        
        existing_request = AccountUpgradeRequest.query.filter_by(
            user_id=current_user.id,
            status='pending'
        ).first()
        
        if existing_request:
            return APIResponse.error("You already have a pending upgrade request", status_code=400)
        
        upgrade_request = AccountUpgradeRequest(
            user_id=current_user.id,
            requested_account_type=requested_type,
            current_account_type=current_user.account_type,
            reason=reason,
            status='pending'
        )
        db.session.add(upgrade_request)
        db.session.commit()
        
        return APIResponse.success(
            data=upgrade_request.to_dict(),
            message="Upgrade request submitted successfully. Admin will review it."
        )
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Upgrade request error: {str(e)}")
        return APIResponse.server_error(str(e))

# ============ BUDGET API ROUTES ============

@bp.route('/api/budget/stats')
@login_required
def api_budget_stats():
    """Get budget statistics"""
    try:
        period = request.args.get('period', 'month')
        current_month = datetime.now().month
        current_year = datetime.now().year
        
        orders_query = Order.query.filter_by(status='approved')
        
        if period == 'month':
            orders_query = orders_query.filter(
                func.extract('month', Order.created_at) == current_month,
                func.extract('year', Order.created_at) == current_year
            )
        elif period == 'quarter':
            three_months_ago = datetime.now() - timedelta(days=90)
            orders_query = orders_query.filter(Order.created_at >= three_months_ago)
        elif period == 'year':
            orders_query = orders_query.filter(func.extract('year', Order.created_at) == current_year)
        
        orders = orders_query.all()
        total_spent = sum(o.total_amount for o in orders)
        total_allocated = 60000
        
        return APIResponse.success(
            data={
                'total_allocated': total_allocated,
                'total_spent': total_spent,
                'total_remaining': total_allocated - total_spent,
                'percentage_used': (total_spent / total_allocated * 100) if total_allocated > 0 else 0,
                'categories': [
                    {'name': 'Consumables', 'allocated': 45000, 'spent': 18450, 'percentage_used': 41},
                    {'name': 'Reagents & Chemicals', 'allocated': 30000, 'spent': 12300, 'percentage_used': 27},
                    {'name': 'Lab Equipment', 'allocated': 25000, 'spent': 9250, 'percentage_used': 20},
                    {'name': 'Pharmacy Stocks', 'allocated': 20000, 'spent': 5000, 'percentage_used': 12}
                ],
                'top_departments': [
                    {'name': 'Pathology Lab', 'spent': 14200, 'order_count': 24},
                    {'name': 'Emergency Care', 'spent': 11850, 'order_count': 18},
                    {'name': 'Radiology', 'spent': 9400, 'order_count': 12}
                ]
            },
            message="Budget stats retrieved"
        )
    except Exception as e:
        current_app.logger.error(f"Budget stats error: {str(e)}")
        return APIResponse.server_error(str(e))

# ============ OTHER API ROUTES ============

@bp.route('/api/sync-queue')
@login_required
def api_sync_queue():
    """Get sync queue items"""
    try:
        sync_items = [
            {
                'id': 1,
                'action_type': 'stock_adjustment',
                'description': 'Inventory update for Amoxicillin (Batch #AX-992)',
                'status': 'pending',
                'created_at': datetime.now().isoformat()
            },
            {
                'id': 2,
                'action_type': 'order_submission',
                'description': 'Order #8829 - MedSource Procurement',
                'status': 'failed',
                'error_message': "Field 'hospital_id' is mandatory",
                'created_at': datetime.now().isoformat()
            }
        ]
        return APIResponse.success(data=sync_items, message="Sync queue retrieved")
    except Exception as e:
        current_app.logger.error(f"Sync queue error: {str(e)}")
        return APIResponse.server_error(str(e))

@bp.route('/api/sync-queue/<int:item_id>/retry', methods=['POST'])
@login_required
def api_sync_retry(item_id):
    """Retry a failed sync item"""
    return APIResponse.success(message="Item queued for retry")

@bp.route('/api/sync-queue/<int:item_id>/delete', methods=['DELETE'])
@login_required
def api_sync_delete(item_id):
    """Delete a sync queue item"""
    return APIResponse.success(message="Item deleted")

@bp.route('/api/sync-queue/retry-all', methods=['POST'])
@login_required
def api_sync_retry_all():
    """Retry all failed sync items"""
    return APIResponse.success(message="All items queued for retry")

@bp.route('/api/scan-history')
@login_required
def api_scan_history():
    """Get scan history"""
    try:
        page = int(request.args.get('page', 1))
        per_page = 25
        
        scans = []
        for i in range(1, 26):
            scans.append({
                'id': i,
                'status': 'authentic' if i % 5 != 0 else 'failed',
                'batch': {
                    'batch_number': f'BATCH-{1000 + i}',
                    'product': {
                        'name': f'Product {i}',
                        'sku': f'SKU-{1000 + i}'
                    }
                },
                'scan_location': 'Main Warehouse',
                'scan_time': datetime.now().isoformat()
            })
        
        return APIResponse.success(
            data={
                'scans': scans,
                'total_scans': 100,
                'filtered_count': len(scans)
            },
            message="Scan history retrieved"
        )
    except Exception as e:
        current_app.logger.error(f"Scan history error: {str(e)}")
        return APIResponse.server_error(str(e))

@bp.route('/api/shipments/<int:shipment_id>')
@login_required
def api_shipment_detail(shipment_id):
    """Get shipment detail"""
    try:
        shipment = {
            'id': shipment_id,
            'shipment_number': f'SH-{99200 + shipment_id}',
            'supplier': 'Steryl Med Africa',
            'carrier': 'DHL Express',
            'expected_date': (datetime.now() + timedelta(days=5)).date().isoformat(),
            'status': 'pending',
            'items': [
                {
                    'id': 1,
                    'product_name': 'Ceftriaxone 1g Injectable',
                    'product_sku': 'MD-223-CTX',
                    'batch_number': 'B23-990',
                    'manufacturer': 'Steryl Med Africa',
                    'expected_quantity': 4,
                    'received_quantity': 0,
                    'status': 'pending'
                },
                {
                    'id': 2,
                    'product_name': 'Ringer\'s Lactate 500ml',
                    'product_sku': 'FL-402-RL',
                    'batch_number': 'RL-402',
                    'manufacturer': 'Steryl Med Africa',
                    'expected_quantity': 8,
                    'received_quantity': 0,
                    'status': 'pending'
                }
            ]
        }
        return APIResponse.success(data=shipment, message="Shipment retrieved")
    except Exception as e:
        current_app.logger.error(f"Shipment detail error: {str(e)}")
        return APIResponse.server_error(str(e))

@bp.route('/api/shipments/<int:shipment_id>/receive', methods=['POST'])
@login_required
def api_receive_shipment(shipment_id):
    """Receive shipment items"""
    try:
        return APIResponse.success(message="Shipment received successfully")
    except Exception as e:
        current_app.logger.error(f"Receive shipment error: {str(e)}")
        return APIResponse.server_error(str(e))

# ============ HEALTH CHECK ============

@bp.route('/health')
def health_check():
    """Health check endpoint"""
    try:
        db.session.execute('SELECT 1')
        return APIResponse.success(
            data={'status': 'healthy', 'database': 'connected'},
            message="System is healthy"
        )
    except Exception as e:
        current_app.logger.error(f"Health check failed: {str(e)}")
        return APIResponse.server_error("Health check failed")