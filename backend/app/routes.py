# STERYL_UP/app/routes.py
from flask import render_template, redirect, url_for, flash, request, jsonify, Blueprint, current_app, session
from flask_login import login_user, login_required, logout_user, current_user
from functools import wraps
from . import db, bcrypt
from .models import (
    User, Product, Batch, Order, OrderItem, Approval, StockMovement, Category,
    Manufacturer, ProductSKU, SupportTicket, PrintQueue, Transaction, MarketplaceListing,
    UserSettings, AccountUpgradeRequest, ManufacturerNotificationState,
    DistributorDemand, DistributorDemandAllocation, DistributorInventory,
    DistributorInventoryReceipt, DistributorSellingPrice,
    DistributorRequest, HospitalRequest, HospitalRequestItem,
    SyncQueue, ScanHistory, Shipment, ShipmentItem, BudgetCategory,
    Department, DeptProductUsage
)
from app.utils.response import APIResponse
from app.utils.validators import UserLoginSchema, UserRegisterSchema, validate_with_schema
from werkzeug.security import check_password_hash
from datetime import datetime, timedelta, date
from sqlalchemy import func, desc
from collections import defaultdict
import hashlib
import json
import re

bp = Blueprint('main', __name__)


def super_admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('main.login'))
        if current_user.role != 'super_admin':
            flash('Super admin access required.', 'error')
            return redirect(url_for('main.dashboard'))
        return f(*args, **kwargs)
    return decorated


def get_current_manufacturer_profile():
    if not current_user.is_authenticated or current_user.account_type != 'manufacturer':
        return None
    return Manufacturer.query.filter_by(user_id=current_user.id).first()


def get_current_distributor_user():
    if not current_user.is_authenticated or current_user.account_type != 'distributor':
        return None
    return current_user


def normalize_sku(raw_sku):
    normalized = re.sub(r'[^A-Z0-9]+', '-', (raw_sku or '').strip().upper())
    return normalized.strip('-')


def get_manufacturer_product(manufacturer_id, product_id):
    return ProductSKU.query.filter_by(id=product_id, manufacturer_id=manufacturer_id).first()


def get_product_active_stock(product):
    return sum((batch.quantity or 0) for batch in (product.batches or []) if batch.status == 'active')


def serialize_manufacturer_product(product):
    product_data = product.to_dict()
    batches = product.batches or []
    active_batches = [batch for batch in batches if batch.status == 'active']
    latest_batch = max(batches, key=lambda batch: batch.created_at or datetime.min) if batches else None
    product_data.update({
        'active_batch_count': len(active_batches),
        'total_batch_count': len(batches),
        'latest_batch_number': latest_batch.batch_number if latest_batch else None,
        'latest_batch_created_at': latest_batch.created_at.isoformat() if latest_batch and latest_batch.created_at else None,
        'updated_at': product.updated_at.isoformat() if product.updated_at else None,
        'created_at': product.created_at.isoformat() if product.created_at else None
    })
    return product_data


def batch_belongs_to_manufacturer(batch, manufacturer_id):
    return bool(batch and batch.product_sku and batch.product_sku.manufacturer_id == manufacturer_id)


def get_manufacturer_batches(manufacturer_id):
    product_ids = [p.id for p in ProductSKU.query.filter_by(manufacturer_id=manufacturer_id).all()]
    if not product_ids:
        return []
    return Batch.query.filter(Batch.product_sku_id.in_(product_ids)).order_by(Batch.created_at.desc()).all()


def get_manufacturer_product_batches(product):
    batches = list(product.batches or [])
    return sorted(
        batches,
        key=lambda batch: (
            0 if batch.status == 'active' else 1,
            batch.expiry_date or date.max,
            batch.created_at or datetime.max,
        )
    )


def is_distributor_user(user):
    return bool(user and user.is_authenticated and user.account_type in {'supplier', 'distributor'})


def get_distributor_user_or_none():
    if not is_distributor_user(current_user):
        return None
    return current_user


def get_supply_batches_fefo(product_sku_id):
    return Batch.query.filter_by(product_sku_id=product_sku_id, status='active').order_by(
        Batch.expiry_date.asc().nulls_last(),
        Batch.created_at.asc()
    ).all()


def allocate_supply_from_batches(product_sku_id, quantity):
    remaining = max(0, int(quantity or 0))
    allocations = []
    if remaining == 0:
        return allocations

    for batch in get_supply_batches_fefo(product_sku_id):
        if remaining <= 0:
            break
        available = batch.quantity or 0
        if available <= 0:
            continue

        used = min(available, remaining)
        batch.quantity = available - used
        if batch.quantity <= 0:
            batch.quantity = 0
            batch.status = 'inactive'
        allocations.append({'batch_id': batch.id, 'batch_number': batch.batch_number, 'used_quantity': used})
        remaining -= used

    if remaining > 0:
        raise ValueError('Insufficient active batch quantity to fulfill this demand')

    return allocations


def is_distributor_account():
    return current_user.is_authenticated and current_user.account_type == 'distributor'


def generate_demand_number():
    stamp = datetime.utcnow().strftime('%Y%m%d%H%M%S')
    today_prefix = datetime.utcnow().strftime('DMD-%Y%m%d')
    sequence = DistributorDemand.query.filter(DistributorDemand.demand_number.like(f'{today_prefix}%')).count() + 1
    return f'DMD-{stamp}-{sequence:03d}'


def get_distributor_catalog_rows(search_term=None, manufacturer_filter=None):
    search_value = (search_term or '').strip().lower()
    manufacturer_value = str(manufacturer_filter).strip() if manufacturer_filter else ''

    products = (
        ProductSKU.query
        .join(Manufacturer, ProductSKU.manufacturer_id == Manufacturer.id)
        .filter(ProductSKU.status == 'active')
        .order_by(ProductSKU.name.asc())
        .all()
    )

    rows = []
    manufacturers = {}

    for product in products:
        manufacturer = product.manufacturer
        if not manufacturer:
            continue

        available_quantity = product.get_total_stock()

        manufacturers[manufacturer.id] = manufacturer.legal_entity_name

        if manufacturer_value and str(manufacturer.id) != manufacturer_value:
            continue

        searchable = ' '.join([
            product.name or '',
            product.sku or '',
            product.category or '',
            manufacturer.legal_entity_name or ''
        ]).lower()
        if search_value and search_value not in searchable:
            continue

        rows.append({
            'id': product.id,
            'name': product.name,
            'sku': product.sku,
            'category': product.category or 'Uncategorized',
            'unit_price': product.unit_price or 0,
            'available_quantity': available_quantity,
            'total_worth': product.get_total_worth(),
            'manufacturer_id': manufacturer.id,
            'manufacturer_name': manufacturer.legal_entity_name,
            'manufacturer_currency': manufacturer.currency,
            'manufacturer_currency_symbol': manufacturer.currency_symbol,
            'reorder_level': product.reorder_level or 0,
            'description': product.description,
        })

    manufacturer_options = [
        {'id': key, 'name': value}
        for key, value in sorted(manufacturers.items(), key=lambda item: item[1].lower())
    ]

    return rows, manufacturer_options


def apply_demand_status_filter(query, status_filter):
    normalized = (status_filter or 'all').strip().lower()
    if normalized == 'pending':
        return query.filter(DistributorDemand.status.in_(['pending', 'approved']))
    if normalized == 'completed':
        return query.filter(DistributorDemand.status == 'completed')
    if normalized == 'approved':
        return query.filter(DistributorDemand.status == 'approved')
    if normalized == 'rejected':
        return query.filter(DistributorDemand.status == 'rejected')
    return query


def get_filtered_demands(distributor_user_id=None, manufacturer_id=None, status_filter='all', start_date=None, end_date=None):
    query = DistributorDemand.query

    if distributor_user_id is not None:
        query = query.filter(DistributorDemand.distributor_user_id == distributor_user_id)
    if manufacturer_id is not None:
        query = query.filter(DistributorDemand.manufacturer_id == manufacturer_id)

    query = apply_demand_status_filter(query, status_filter)

    if start_date:
        start_dt = datetime.combine(start_date, datetime.min.time())
        query = query.filter(DistributorDemand.requested_at >= start_dt)
    if end_date:
        end_dt = datetime.combine(end_date + timedelta(days=1), datetime.min.time())
        query = query.filter(DistributorDemand.requested_at < end_dt)

    return query.order_by(desc(DistributorDemand.requested_at), desc(DistributorDemand.id)).all()


def summarize_demands(demands):
    return {
        'total_count': len(demands),
        'pending_count': sum(1 for demand in demands if demand.status in {'pending', 'approved'}),
        'completed_count': sum(1 for demand in demands if demand.status in {'supplied', 'completed'}),
        'rejected_count': sum(1 for demand in demands if demand.status == 'rejected'),
        'requested_units': sum(demand.requested_quantity or 0 for demand in demands),
        'supplied_units': sum(demand.supplied_quantity or 0 for demand in demands),
        'total_amount': sum(demand.total_amount or 0 for demand in demands),
    }


def get_distributor_inventory_rows(distributor_user_id):
    items = (
        DistributorInventory.query
        .filter_by(distributor_user_id=distributor_user_id)
        .order_by(desc(DistributorInventory.updated_at), desc(DistributorInventory.id))
        .all()
    )

    rows = []
    for item in items:
        product = item.product_sku
        manufacturer = item.manufacturer
        cost_price = (product.unit_price if product else 0) or 0
        pricing = DistributorSellingPrice.query.filter_by(
            distributor_user_id=distributor_user_id,
            manufacturer_id=item.manufacturer_id,
            product_sku_id=item.product_sku_id,
        ).first()
        latest_receipt = DistributorInventoryReceipt.query.filter_by(
            distributor_user_id=distributor_user_id,
            manufacturer_id=item.manufacturer_id,
            product_sku_id=item.product_sku_id,
        ).order_by(DistributorInventoryReceipt.created_at.desc()).first()
        selling = pricing.selling_price if pricing else 0
        qty = item.quantity or 0
        inventory_value = round(qty * cost_price, 2)
        profit_per_unit = round(selling - cost_price, 4) if selling else None
        total_profit = round(profit_per_unit * qty, 2) if profit_per_unit is not None else None
        rows.append({
            'id': item.id,
            'product_name': product.name if product else 'Unknown Product',
            'sku': product.sku if product else 'N/A',
            'category': product.category if product and product.category else 'Uncategorized',
            'manufacturer_name': manufacturer.legal_entity_name if manufacturer else 'Unknown Manufacturer',
            'manufacturer_currency_symbol': manufacturer.currency_symbol if manufacturer else '$',
            'quantity': qty,
            'cost_price': cost_price,
            'selling_price': selling,
            'profit_per_unit': profit_per_unit,
            'total_profit': total_profit,
            'inventory_value': inventory_value,
            'latest_batch_number': latest_receipt.batch_number if latest_receipt else None,
            'latest_manufactured_date': latest_receipt.manufactured_date if latest_receipt else None,
            'latest_expiry_date': latest_receipt.expiry_date if latest_receipt else None,
            'batch_location': None,
            'last_received_at': latest_receipt.created_at if latest_receipt else None,
        })

    return rows


def fulfill_distributor_demand(demand, actor_id):
    if demand.status == 'completed' or (demand.supplied_quantity or 0) > 0:
        raise ValueError('This demand has already been supplied.')

    quantity_to_supply = demand.approved_quantity or demand.requested_quantity
    if quantity_to_supply <= 0:
        raise ValueError('Approved quantity must be greater than zero before supply.')

    product = demand.product_sku
    if not product:
        raise ValueError('The requested product no longer exists.')

    batches = [
        batch for batch in get_manufacturer_product_batches(product)
        if batch.status == 'active' and (batch.quantity or 0) > 0
    ]
    available_quantity = sum(batch.quantity or 0 for batch in batches)
    if available_quantity < quantity_to_supply:
        raise ValueError(f'Only {available_quantity} active units are available for supply.')

    allocated_batches = []
    remaining_quantity = quantity_to_supply
    for batch in batches:
        if remaining_quantity <= 0:
            break

        allocated_quantity = min(batch.quantity or 0, remaining_quantity)
        if allocated_quantity <= 0:
            continue

        batch.quantity = (batch.quantity or 0) - allocated_quantity
        allocation_record = DistributorDemandAllocation(
            demand_id=demand.id,
            batch_id=batch.id,
            quantity=allocated_quantity
        )
        db.session.add(allocation_record)
        db.session.flush()
        db.session.add(StockMovement(
            batch_id=batch.id,
            movement_type='distributor_supply',
            quantity=allocated_quantity,
            from_location=demand.manufacturer.legal_entity_name if demand.manufacturer else 'Manufacturer Catalog',
            to_location=f'Distributor {demand.distributor.first_name} {demand.distributor.last_name}' if demand.distributor else 'Distributor Inventory',
            reference_id=demand.demand_number,
            notes=f'Supplied against distributor demand {demand.demand_number}',
            user_id=actor_id
        ))
        allocated_batches.append({
            'batch': batch,
            'quantity': allocated_quantity,
            'allocation_id': allocation_record.id,
        })
        remaining_quantity -= allocated_quantity

    if not allocated_batches:
        raise ValueError('Unable to allocate any active batches for this demand.')

    primary_batch = allocated_batches[0]['batch']

    inventory_item = DistributorInventory.query.filter_by(
        distributor_user_id=demand.distributor_user_id,
        manufacturer_id=demand.manufacturer_id,
        product_sku_id=demand.product_sku_id
    ).first()

    if not inventory_item:
        inventory_item = DistributorInventory(
            distributor_user_id=demand.distributor_user_id,
            manufacturer_id=demand.manufacturer_id,
            product_sku_id=demand.product_sku_id,
            quantity=0
        )
        db.session.add(inventory_item)

    inventory_item.quantity = (inventory_item.quantity or 0) + quantity_to_supply

    unit_cost = demand.unit_price or (demand.product_sku.unit_price if demand.product_sku else 0) or 0
    for allocation in allocated_batches:
        batch = allocation['batch']
        allocated_qty = allocation['quantity']

        receipt = DistributorInventoryReceipt(
            distributor_user_id=demand.distributor_user_id,
            manufacturer_id=demand.manufacturer_id,
            product_sku_id=demand.product_sku_id,
            demand_id=demand.id,
            allocation_id=allocation['allocation_id'],
            batch_id=batch.id,
            batch_number=batch.batch_number,
            manufactured_date=batch.manufacturing_date,
            expiry_date=batch.expiry_date,
            quantity=allocated_qty,
            unit_cost=unit_cost,
        )
        db.session.add(receipt)

    demand.approved_quantity = quantity_to_supply
    demand.supplied_quantity = quantity_to_supply
    demand.payment_status = 'validated'
    demand.status = 'supplied'
    demand.supplied_at = datetime.utcnow()
    demand.completed_at = demand.supplied_at
    demand.recalculate_total()

    return quantity_to_supply


def parse_report_date(raw_value, fallback):
    if not raw_value:
        return fallback
    try:
        return datetime.strptime(raw_value, '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return fallback


def build_manufacturer_report(manufacturer, start_date, end_date, status_filter):
    start_dt = datetime.combine(start_date, datetime.min.time())
    end_dt = datetime.combine(end_date + timedelta(days=1), datetime.min.time())

    products = ProductSKU.query.filter_by(manufacturer_id=manufacturer.id).order_by(ProductSKU.name.asc()).all()
    product_map = {product.id: product for product in products}

    batches = (
        Batch.query
        .join(ProductSKU, Batch.product_sku_id == ProductSKU.id)
        .filter(ProductSKU.manufacturer_id == manufacturer.id)
        .filter(Batch.created_at >= start_dt, Batch.created_at < end_dt)
        .all()
    )

    if status_filter in {'active', 'inactive'}:
        batches = [batch for batch in batches if batch.status == status_filter]

    batches = sorted(
        batches,
        key=lambda batch: (
            batch.expiry_date or date.max,
            batch.created_at or datetime.max,
            batch.batch_number or ''
        )
    )

    product_rows_map = {}
    batch_rows = []
    total_units = 0
    total_worth = 0
    active_batch_count = 0
    inactive_batch_count = 0

    for batch in batches:
        product = product_map.get(batch.product_sku_id)
        if not product:
            continue

        batch_quantity = batch.quantity or 0
        batch_value = (product.unit_price or 0) * batch_quantity
        total_units += batch_quantity
        total_worth += batch_value
        active_batch_count += 1 if batch.status == 'active' else 0
        inactive_batch_count += 1 if batch.status == 'inactive' else 0

        product_row = product_rows_map.setdefault(product.id, {
            'product_id': product.id,
            'name': product.name,
            'sku': product.sku,
            'category': product.category or 'Uncategorized',
            'status': product.status,
            'batch_count': 0,
            'units': 0,
            'worth': 0,
            'active_batches': 0,
            'inactive_batches': 0,
            'latest_batch_created_at': None,
        })
        product_row['batch_count'] += 1
        product_row['units'] += batch_quantity
        product_row['worth'] += batch_value
        product_row['active_batches'] += 1 if batch.status == 'active' else 0
        product_row['inactive_batches'] += 1 if batch.status == 'inactive' else 0

        if not product_row['latest_batch_created_at'] or ((batch.created_at or datetime.min) > product_row['latest_batch_created_at']):
            product_row['latest_batch_created_at'] = batch.created_at or datetime.min

        batch_rows.append({
            'batch_id': batch.id,
            'batch_number': batch.batch_number,
            'product_name': product.name,
            'sku': product.sku,
            'status': batch.status,
            'quantity': batch_quantity,
            'batch_value': batch_value,
            'created_at': batch.created_at,
            'manufacturing_date': batch.manufacturing_date,
            'expiry_date': batch.expiry_date,
        })

    product_rows = sorted(
        product_rows_map.values(),
        key=lambda item: (-(item['worth'] or 0), item['name'])
    )

    transactions = (
        Transaction.query
        .filter(Transaction.manufacturer_id == manufacturer.id)
        .filter(Transaction.created_at >= start_dt, Transaction.created_at < end_dt)
        .order_by(desc(Transaction.created_at))
        .all()
    )
    demand_rows_map = defaultdict(lambda: {'service_type': 'General', 'transaction_count': 0, 'batch_volume': 0, 'amount': 0})
    for transaction in transactions:
        service_key = (transaction.service_type or 'General').strip() or 'General'
        demand_row = demand_rows_map[service_key]
        demand_row['service_type'] = service_key
        demand_row['transaction_count'] += 1
        demand_row['batch_volume'] += transaction.batch_volume or 0
        demand_row['amount'] += transaction.amount or 0

    demand_rows = sorted(demand_rows_map.values(), key=lambda item: (-item['amount'], item['service_type']))

    listings = MarketplaceListing.query.filter_by(supplier_id=manufacturer.id).all()
    if status_filter in {'active', 'inactive'}:
        listings = [listing for listing in listings if listing.status == status_filter]

    summary = {
        'product_count': len(product_rows),
        'batch_count': len(batch_rows),
        'total_units': total_units,
        'total_worth': total_worth,
        'active_batch_count': active_batch_count,
        'inactive_batch_count': inactive_batch_count,
        'transaction_count': len(transactions),
        'transaction_amount': sum(transaction.amount or 0 for transaction in transactions),
        'transaction_volume': sum(transaction.batch_volume or 0 for transaction in transactions),
        'listing_count': len(listings),
        'listing_quantity': sum(listing.available_quantity or 0 for listing in listings),
    }

    return {
        'summary': summary,
        'product_rows': product_rows,
        'batch_rows': batch_rows,
        'demand_rows': demand_rows,
        'transactions': transactions[:8],
    }


def parse_status_filter(raw_value, allowed_values, default='both'):
    value = (raw_value or default).strip().lower()
    return value if value in allowed_values else default


def parse_quantity(raw_value):
    try:
        return int(raw_value or 0)
    except (TypeError, ValueError):
        return None


def serialize_distributor_demand(demand):
    demand_data = demand.to_dict()
    product = demand.product_sku
    manufacturer = demand.manufacturer
    demand_data.update({
        'available_stock': get_product_active_stock(product) if product else 0,
        'manufacturer_currency': manufacturer.currency if manufacturer else 'USD',
        'manufacturer_currency_symbol': manufacturer.currency_symbol if manufacturer else '$',
    })
    return demand_data


def consume_product_stock_fefo(product, requested_quantity):
    remaining_quantity = requested_quantity
    consumed_batches = []

    for batch in get_manufacturer_product_batches(product):
        if batch.status != 'active' or (batch.quantity or 0) <= 0:
            continue

        take_quantity = min(batch.quantity or 0, remaining_quantity)
        if take_quantity <= 0:
            continue

        batch.quantity = (batch.quantity or 0) - take_quantity
        consumed_batches.append({
            'batch_id': batch.id,
            'batch_number': batch.batch_number,
            'quantity': take_quantity,
        })
        remaining_quantity -= take_quantity

        if remaining_quantity <= 0:
            break

    if remaining_quantity > 0:
        raise ValueError('Not enough active stock to fulfill this request')

    return consumed_batches


@bp.route('/manufacturer/catalog/<int:product_id>')
@login_required
def manufacturer_product_detail(product_id):
    """Render the full manufacturer-scoped product detail page."""
    manufacturer = get_current_manufacturer_profile()
    if not manufacturer:
        flash('Manufacturer access required.', 'error')
        return redirect(url_for('main.manufacturer_login_page'))

    product = get_manufacturer_product(manufacturer.id, product_id)
    if not product:
        flash('Product not found.', 'error')
        return redirect(url_for('main.manufacturer_skus'))

    batches = get_manufacturer_product_batches(product)
    return render_template(
        'manufacturer/product-details.html',
        product=product,
        manufacturer=manufacturer,
        batches=batches,
        manufacturer_page_title='Product Details',
        manufacturer_primary_action_href=url_for('main.manufacturer_skus'),
        manufacturer_primary_action_label='Back to Catalog',
        manufacturer_primary_action_icon='arrow_back'
    )


def build_manufacturer_notification_signature(item):
    raw_signature = '|'.join([
        str(item.get('id', '')),
        str(item.get('count', 0)),
        str(item.get('title', '')),
        str(item.get('message', '')),
        str(item.get('section', '')),
        str(item.get('priority', '')),
        str(item.get('variant', '')),
    ])
    return hashlib.sha256(raw_signature.encode('utf-8')).hexdigest()


def serialize_manufacturer_notifications(manufacturer):
    notifications = build_manufacturer_notifications(manufacturer)
    state_rows = ManufacturerNotificationState.query.filter_by(
        user_id=current_user.id,
        manufacturer_id=manufacturer.id
    ).all()
    state_map = {row.notification_id: row for row in state_rows}

    unread_count = 0
    unread_groups = 0

    for item in notifications:
        signature = build_manufacturer_notification_signature(item)
        state = state_map.get(item['id'])
        is_read = bool(state and state.signature == signature and state.read_at)
        item['signature'] = signature
        item['is_read'] = is_read
        if not is_read:
            unread_count += item['count']
            unread_groups += 1

    summary = {
        'total_groups': len(notifications),
        'total_alerts': sum(item['count'] for item in notifications),
        'unread_groups': unread_groups,
        'critical_actions': sum(item['count'] for item in notifications if not item['is_read'] and item['priority'] <= 2),
        'label_actions': sum(item['count'] for item in notifications if not item['is_read'] and item['section'] == 'Labels'),
        'support_actions': sum(item['count'] for item in notifications if not item['is_read'] and item['section'] == 'Support')
    }

    return {
        'items': notifications,
        'unread_count': unread_count,
        'summary': summary
    }


def upsert_manufacturer_notification_state(manufacturer_id, notification_id, signature):
    state = ManufacturerNotificationState.query.filter_by(
        user_id=current_user.id,
        manufacturer_id=manufacturer_id,
        notification_id=notification_id
    ).first()

    if not state:
        state = ManufacturerNotificationState(
            user_id=current_user.id,
            manufacturer_id=manufacturer_id,
            notification_id=notification_id,
            signature=signature,
            read_at=datetime.utcnow()
        )
        db.session.add(state)
        return state

    state.signature = signature
    state.read_at = datetime.utcnow()
    return state


def build_manufacturer_notifications(manufacturer):
    notifications = []
    if not manufacturer:
        return notifications

    products = ProductSKU.query.filter_by(manufacturer_id=manufacturer.id).all()
    batches = get_manufacturer_batches(manufacturer.id)
    batch_ids = [batch.id for batch in batches]
    print_items = PrintQueue.query.filter(PrintQueue.batch_id.in_(batch_ids)).all() if batch_ids else []
    open_tickets = SupportTicket.query.filter_by(user_id=current_user.id, status='open').count()

    pending_products = len([product for product in products if product.status == 'pending'])
    if pending_products:
        notifications.append({
            'id': 'pending-products',
            'title': 'Products pending review',
            'message': f'{pending_products} catalog item(s) are still pending review.',
            'variant': 'warning',
            'section': 'Catalog',
            'priority': 2,
            'icon': 'inventory_2',
            'href': url_for('main.manufacturer_skus'),
            'action_label': 'Review catalog',
            'count': pending_products
        })

    ready_labels = len([item for item in print_items if item.status == 'ready'])
    if ready_labels:
        notifications.append({
            'id': 'ready-labels',
            'title': 'Labels ready for print',
            'message': f'{ready_labels} label package(s) are ready to download or print.',
            'variant': 'success',
            'section': 'Labels',
            'priority': 1,
            'icon': 'print',
            'href': url_for('main.manufacturer_print_queue'),
            'action_label': 'Open print queue',
            'count': ready_labels
        })

    pending_labels = len([item for item in print_items if item.status == 'pending'])
    if pending_labels:
        notifications.append({
            'id': 'pending-labels',
            'title': 'Labels awaiting processing',
            'message': f'{pending_labels} batch label(s) have not been prepared yet.',
            'variant': 'info',
            'section': 'Labels',
            'priority': 3,
            'icon': 'schedule',
            'href': url_for('main.manufacturer_print_queue'),
            'action_label': 'View queue',
            'count': pending_labels
        })

    today = datetime.utcnow().date()
    expiring_batches = len([
        batch for batch in batches
        if batch.expiry_date and 0 <= (batch.expiry_date - today).days <= 90
    ])
    if expiring_batches:
        notifications.append({
            'id': 'expiring-batches',
            'title': 'Batches expiring soon',
            'message': f'{expiring_batches} active batch(es) expire within the next 90 days.',
            'variant': 'warning',
            'section': 'Compliance',
            'priority': 1,
            'icon': 'warning',
            'href': url_for('main.manufacturer_batches'),
            'action_label': 'Inspect batches',
            'count': expiring_batches
        })

    if open_tickets:
        notifications.append({
            'id': 'open-tickets',
            'title': 'Open support tickets',
            'message': f'{open_tickets} support ticket(s) are still open for your account.',
            'variant': 'info',
            'section': 'Support',
            'priority': 4,
            'icon': 'support_agent',
            'href': url_for('main.support_tickets'),
            'action_label': 'View tickets',
            'count': open_tickets
        })

    notifications.sort(key=lambda item: (item['priority'], -item['count'], item['title']))
    return notifications

# ============ PAGE ROUTES ============

@bp.route('/')
@bp.route('/index')
def index():
    return render_template('index.html')

@bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        return render_template('login.html')

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

            if password_valid:
                # Super admins bypass account_status check
                if user.role == 'super_admin':
                    login_user(user, remember=validated_data['remember'])
                    return APIResponse.success(
                        data={'user': user.to_dict()},
                        message="Login successful",
                        meta={'redirect': url_for('main.admin_registrations')}
                    )

                status = getattr(user, 'account_status', 'approved')
                if status == 'pending':
                    return APIResponse.error(
                        "Your registration is under review. You will be notified once approved.", 403,
                        error_code="ACCOUNT_PENDING"
                    )
                if status == 'rejected':
                    reason = user.rejection_reason or "Please contact support for details."
                    return APIResponse.error(
                        f"Your registration was not approved. {reason}", 403,
                        error_code="ACCOUNT_REJECTED"
                    )
                if status == 'suspended':
                    return APIResponse.error(
                        "Your account has been suspended. Please contact support.", 403,
                        error_code="ACCOUNT_SUSPENDED"
                    )

                login_user(user, remember=validated_data['remember'])
                current_app.logger.info(f"User {user.email} logged in successfully")
                # Route each account type to its dedicated workspace
                account_type = getattr(user, 'account_type', 'hospital')
                if account_type == 'manufacturer':
                    redirect_url = url_for('main.manufacturer_skus')
                elif account_type == 'distributor':
                    redirect_url = url_for('main.distributor_marketplace')
                else:
                    redirect_url = url_for('main.dashboard')
                return APIResponse.success(
                    data={'user': user.to_dict()},
                    message="Login successful",
                    meta={'redirect': redirect_url}
                )

        current_app.logger.warning(f"Failed login attempt for email: {validated_data['email']}")
        return APIResponse.unauthorized("Invalid email or password")

    except Exception as e:
        current_app.logger.error(f"Login error: {str(e)}", exc_info=True)
        return APIResponse.server_error("An error occurred during login")

@bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'GET':
        return render_template('register.html')

    try:
        data = request.get_json()
        if not data:
            return APIResponse.error("Invalid request format", 400)

        is_valid, validated_data, errors = validate_with_schema(UserRegisterSchema(), data)
        if not is_valid:
            current_app.logger.warning(f"Registration validation failed: {errors}")
            return APIResponse.validation_error(errors)

        existing_user = User.query.filter_by(email=validated_data['email'].lower()).first()
        if existing_user:
            return APIResponse.conflict("Email already registered. Please login instead.")

        new_user = User(
            first_name=validated_data['first_name'],
            last_name=validated_data['last_name'],
            email=validated_data['email'],
            password=validated_data['password'],
            phone=validated_data.get('phone'),
            country=validated_data['country'],
            account_type=validated_data['account_type'],
            organization_name=validated_data.get('organization_name'),
            license_number=validated_data.get('license_number'),
            business_address=validated_data.get('business_address'),
        )
        # The person registering the org is always its admin
        new_user.role = 'admin'
        # New registrations always start as pending (awaiting SUPER_ADMIN approval)
        new_user.account_status = 'pending'

        db.session.add(new_user)
        db.session.commit()
        current_app.logger.info(f"New organization registered (pending): {new_user.email} ({new_user.account_type})")

        return APIResponse.success(
            data={'user': new_user.to_dict()},
            message="Registration submitted successfully. A super admin will review and approve your account.",
            status_code=201,
            meta={'pending': True}
        )

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Registration error: {str(e)}", exc_info=True)
        return APIResponse.server_error("An error occurred during registration")

@bp.route('/logout')
@login_required
def logout():
    """Handle user logout"""
    redirect_endpoint = 'main.manufacturer_login_page' if current_user.account_type == 'manufacturer' else 'main.login'
    logout_user()
    flash('You have been logged out successfully.', 'info')
    return redirect(url_for(redirect_endpoint))

# ============ STATIC PAGE ROUTES ============

@bp.route('/about')
def about():
    return render_template('about.html')

@bp.route('/demo')
def demo():
    return render_template('demo.html')

@bp.route('/invest')
def invest():
    return render_template('invest.html')

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
    if current_user.account_type == 'manufacturer':
        return redirect(url_for('main.manufacturer_skus'))
    if is_distributor_account():
        return redirect(url_for('main.distributor_marketplace'))
    return render_template('dashboard/procurement.html')


@bp.route('/distributor/marketplace')
@bp.route('/distributor/catalog')
@login_required
def distributor_marketplace():
    if not is_distributor_account():
        flash('Distributor access required.', 'error')
        return redirect(url_for('main.dashboard'))

    return render_template('distributor/catalog.html')


@bp.route('/distributor/demands')
@login_required
def distributor_demands():
    if not is_distributor_account():
        flash('Distributor access required.', 'error')
        return redirect(url_for('main.dashboard'))

    today = date.today()
    default_start = today - timedelta(days=29)
    start_date = parse_report_date(request.args.get('start_date'), default_start)
    end_date = parse_report_date(request.args.get('end_date'), today)
    if start_date > end_date:
        start_date, end_date = end_date, start_date

    status_filter = (request.args.get('status') or 'all').strip().lower()
    demands = get_filtered_demands(
        distributor_user_id=current_user.id,
        status_filter=status_filter,
        start_date=start_date,
        end_date=end_date,
    )

    return render_template(
        'distributor/demands.html',
        distributor_demands=demands,
        distributor_summary=summarize_demands(demands),
        distributor_filters={
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat(),
            'status': status_filter,
        }
    )


@bp.route('/distributor/inventory')
@login_required
def distributor_inventory():
    if not is_distributor_account():
        flash('Distributor access required.', 'error')
        return redirect(url_for('main.dashboard'))

    inventory_rows = get_distributor_inventory_rows(current_user.id)
    inventory_total_value = sum((row.get('inventory_value') or 0) for row in inventory_rows)
    priced_rows = [row for row in inventory_rows if row.get('selling_price')]
    priced_units = sum((row.get('quantity') or 0) for row in priced_rows)
    total_profit = sum((row.get('total_profit') or 0) for row in inventory_rows)
    avg_profit_per_priced_unit = (total_profit / priced_units) if priced_units else 0

    return render_template(
        'distributor/inventory.html',
        inventory_rows=inventory_rows,
        inventory_total_units=sum(row['quantity'] for row in inventory_rows),
        inventory_total_value=inventory_total_value,
        inventory_total_profit=total_profit,
        inventory_priced_lines=len(priced_rows),
        inventory_avg_profit_per_unit=avg_profit_per_priced_unit,
    )


@bp.route('/distributor/inventory/<int:inventory_id>/price', methods=['POST'])
@login_required
def distributor_update_selling_price(inventory_id):
    if not is_distributor_account():
        flash('Distributor access required.', 'error')
        return redirect(url_for('main.dashboard'))

    inventory_item = DistributorInventory.query.filter_by(
        id=inventory_id,
        distributor_user_id=current_user.id,
    ).first()
    if not inventory_item:
        flash('Inventory item not found.', 'error')
        return redirect(url_for('main.distributor_inventory'))

    try:
        selling_price = float(request.form.get('selling_price', 0))
    except (TypeError, ValueError):
        flash('Selling price must be a valid number.', 'error')
        return redirect(url_for('main.distributor_inventory'))

    if selling_price <= 0:
        flash('Selling price must be greater than zero.', 'error')
        return redirect(url_for('main.distributor_inventory'))

    pricing = DistributorSellingPrice.query.filter_by(
        distributor_user_id=current_user.id,
        manufacturer_id=inventory_item.manufacturer_id,
        product_sku_id=inventory_item.product_sku_id,
    ).first()
    if not pricing:
        pricing = DistributorSellingPrice(
            distributor_user_id=current_user.id,
            manufacturer_id=inventory_item.manufacturer_id,
            product_sku_id=inventory_item.product_sku_id,
            selling_price=selling_price,
        )
        db.session.add(pricing)
    else:
        pricing.selling_price = selling_price

    db.session.commit()
    flash('Selling price updated successfully.', 'success')
    return redirect(url_for('main.distributor_inventory'))


@bp.route('/distributor/demands/create', methods=['POST'])
@login_required
def distributor_create_demand():
    if not is_distributor_account():
        flash('Distributor access required.', 'error')
        return redirect(url_for('main.dashboard'))

    try:
        product_id = int(request.form.get('product_id', 0))
        requested_quantity = int(request.form.get('quantity', 0))
    except (TypeError, ValueError):
        flash('Enter a valid product and quantity.', 'error')
        return redirect(url_for('main.distributor_marketplace'))

    notes = (request.form.get('notes') or '').strip() or None
    product = ProductSKU.query.filter_by(id=product_id, status='active').first()
    if not product:
        flash('The selected manufacturer product is unavailable.', 'error')
        return redirect(url_for('main.distributor_marketplace'))

    available_quantity = product.get_total_stock()
    if requested_quantity <= 0:
        flash('Requested quantity must be greater than zero.', 'error')
        return redirect(url_for('main.distributor_marketplace'))

    demand = DistributorDemand(
        demand_number=generate_demand_number(),
        manufacturer_id=product.manufacturer_id,
        distributor_user_id=current_user.id,
        product_sku_id=product.id,
        requested_quantity=requested_quantity,
        unit_price=product.unit_price or 0,
        status='pending',
        notes=notes,
        payment_status='pending'
    )
    demand.recalculate_total()

    db.session.add(demand)
    db.session.commit()

    flash(f'Demand {demand.demand_number} was submitted to {product.manufacturer.legal_entity_name}. Validate payment to move it forward.', 'success')
    return redirect(url_for('main.distributor_demands'))


@bp.route('/distributor/demands/<int:demand_id>/payment', methods=['POST'])
@login_required
def distributor_validate_payment(demand_id):
    if not is_distributor_account():
        flash('Distributor access required.', 'error')
        return redirect(url_for('main.dashboard'))

    demand = DistributorDemand.query.filter_by(id=demand_id, distributor_user_id=current_user.id).first()
    if not demand:
        flash('Demand request not found.', 'error')
        return redirect(url_for('main.distributor_demands'))

    if demand.status in {'completed', 'rejected'}:
        flash('This demand can no longer be updated for payment.', 'error')
        return redirect(url_for('main.distributor_demands'))

    demand.payment_status = 'validated'
    demand.status = 'payment_validated'
    demand.payment_validated_at = datetime.utcnow()
    db.session.commit()

    flash(f'Payment validated for demand {demand.demand_number}. The manufacturer can now approve or supply it.', 'success')
    return redirect(url_for('main.distributor_demands'))

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

@bp.route('/orders')
@login_required
def orders():
    return render_template('dashboard/orders.html')

@bp.route('/inventory')
@login_required
def inventory():
    return render_template('dashboard/inventory.html')

@bp.route('/departments')
@login_required
def departments():
    return render_template('dashboard/departments.html')

# ============ DEPARTMENT API ROUTES ============

@bp.route('/api/departments', methods=['GET', 'POST'])
@login_required
def api_departments():
    """List or create departments for the current org admin."""
    try:
        if request.method == 'GET':
            # Org admin sees their own depts; dept staff sees just their dept
            if current_user.role == 'admin' or current_user.role == 'super_admin':
                depts = Department.query.filter_by(org_user_id=current_user.id).order_by(Department.name).all()
            else:
                # Find which org the user belongs to via department_id
                if current_user.department_id:
                    dept = Department.query.get(current_user.department_id)
                    depts = [dept] if dept else []
                else:
                    depts = []
            return APIResponse.success(data=[d.to_dict() for d in depts], message="Departments retrieved")

        elif request.method == 'POST':
            if current_user.role not in ('admin', 'super_admin'):
                return APIResponse.forbidden("Only org admins can create departments")
            data = request.get_json()
            name = (data.get('name') or '').strip()
            if not name:
                return APIResponse.validation_error({'name': 'Department name is required'})
            dept = Department(
                name=name,
                org_user_id=current_user.id,
                org_type=current_user.account_type
            )
            db.session.add(dept)
            db.session.commit()
            return APIResponse.success(data=dept.to_dict(), message="Department created", status_code=201)
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Department API error: {str(e)}")
        return APIResponse.server_error(str(e))


@bp.route('/api/departments/<int:dept_id>', methods=['DELETE', 'PUT'])
@login_required
def api_department_detail(dept_id):
    """Update or delete a department."""
    try:
        dept = Department.query.get_or_404(dept_id)
        if dept.org_user_id != current_user.id and current_user.role != 'super_admin':
            return APIResponse.forbidden("Access denied")

        if request.method == 'DELETE':
            if dept.members.count() > 0:
                return APIResponse.error("Cannot delete a department that has members", 400)
            db.session.delete(dept)
            db.session.commit()
            return APIResponse.success(message="Department deleted")

        elif request.method == 'PUT':
            data = request.get_json()
            name = (data.get('name') or '').strip()
            if name:
                dept.name = name
            db.session.commit()
            return APIResponse.success(data=dept.to_dict(), message="Department updated")
    except Exception as e:
        db.session.rollback()
        return APIResponse.server_error(str(e))


@bp.route('/api/departments/<int:dept_id>/members', methods=['GET'])
@login_required
def api_dept_members(dept_id):
    """List members of a department."""
    try:
        dept = Department.query.get_or_404(dept_id)
        if dept.org_user_id != current_user.id and current_user.department_id != dept_id:
            return APIResponse.forbidden("Access denied")
        members = dept.members.all()
        data = [{
            'id': m.id,
            'name': f"{m.first_name} {m.last_name}",
            'email': m.email,
            'role': m.role,
        } for m in members]
        return APIResponse.success(data=data, message="Members retrieved")
    except Exception as e:
        return APIResponse.server_error(str(e))


@bp.route('/api/departments/<int:dept_id>/assign-member', methods=['POST'])
@login_required
def api_dept_assign_member(dept_id):
    """Assign a user to a department (org admin only)."""
    try:
        if current_user.role not in ('admin', 'super_admin'):
            return APIResponse.forbidden("Only org admins can assign members")
        dept = Department.query.get_or_404(dept_id)
        if dept.org_user_id != current_user.id:
            return APIResponse.forbidden("Access denied")
        data = request.get_json()
        user_id = data.get('user_id')
        member = User.query.get(user_id)
        if not member:
            return APIResponse.not_found("User")
        member.department_id = dept_id
        db.session.commit()
        return APIResponse.success(message=f"{member.first_name} assigned to {dept.name}")
    except Exception as e:
        db.session.rollback()
        return APIResponse.server_error(str(e))


@bp.route('/api/departments/<int:dept_id>/remove-member/<int:user_id>', methods=['DELETE'])
@login_required
def api_dept_remove_member(dept_id, user_id):
    """Remove a user from a department (org admin only)."""
    try:
        if current_user.role not in ('admin', 'super_admin'):
            return APIResponse.forbidden("Only org admins can remove members")
        dept = Department.query.get_or_404(dept_id)
        if dept.org_user_id != current_user.id:
            return APIResponse.forbidden("Access denied")
        member = User.query.get(user_id)
        if member and member.department_id == dept_id:
            member.department_id = None
            db.session.commit()
        return APIResponse.success(message="Member removed from department")
    except Exception as e:
        db.session.rollback()
        return APIResponse.server_error(str(e))


@bp.route('/api/dept-orders', methods=['GET'])
@login_required
def api_dept_orders():
    """Get department order requests.
    - Org admin: sees all dept requests from their org.
    - Dept staff: sees only their dept's requests.
    """
    try:
        if current_user.role in ('admin', 'super_admin'):
            dept_ids = [d.id for d in Department.query.filter_by(org_user_id=current_user.id).all()]
            orders = Order.query.filter(
                Order.is_dept_request == True,
                Order.dept_id.in_(dept_ids)
            ).order_by(desc(Order.created_at)).all()
        elif current_user.department_id:
            orders = Order.query.filter_by(
                dept_id=current_user.department_id,
                is_dept_request=True
            ).order_by(desc(Order.created_at)).all()
        else:
            orders = []

        result = []
        for o in orders:
            d = o.to_dict()
            if o.dept_id:
                dept = Department.query.get(o.dept_id)
                d['dept_name'] = dept.name if dept else None
            result.append(d)

        return APIResponse.success(data=result, message="Dept orders retrieved")
    except Exception as e:
        current_app.logger.error(f"Dept orders API error: {str(e)}")
        return APIResponse.server_error(str(e))


@bp.route('/api/dept-orders/submit', methods=['POST'])
@login_required
def api_dept_order_submit():
    """Dept staff submits an order to the dept pool."""
    try:
        if not current_user.department_id:
            return APIResponse.error("You must be assigned to a department to submit a dept order", 400)

        data = request.get_json()
        order_number = f"DORD-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        order = Order(
            order_number=order_number,
            requester_id=current_user.id,
            order_type='purchase',
            notes=data.get('notes', ''),
            dept_id=current_user.department_id,
            is_dept_request=True,
            status='dept_pending'
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
        return APIResponse.success(data=order.to_dict(), message="Department order submitted", status_code=201)
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Dept order submit error: {str(e)}")
        return APIResponse.server_error(str(e))


@bp.route('/api/dept-orders/consolidate', methods=['POST'])
@login_required
def api_dept_orders_consolidate():
    """Org admin consolidates selected dept orders into one order to the distributor."""
    try:
        if current_user.role not in ('admin', 'super_admin'):
            return APIResponse.forbidden("Only org admins can consolidate orders")

        data = request.get_json()
        order_ids = data.get('order_ids', [])
        notes = data.get('notes', '')

        if not order_ids:
            return APIResponse.validation_error({'order_ids': 'Select at least one order to consolidate'})

        # Find the Steryl Admin distributor
        distributor = User.query.filter_by(account_type='distributor').first()
        if not distributor:
            return APIResponse.error("No distributor found in the system. Please contact support.", 400)

        # Gather all items from selected dept orders
        combined_items = {}
        for oid in order_ids:
            o = Order.query.get(oid)
            if not o or o.dept_id is None:
                continue
            dept = Department.query.get(o.dept_id)
            if not dept or dept.org_user_id != current_user.id:
                continue
            for item in o.items:
                key = item.product_id
                if key in combined_items:
                    combined_items[key]['quantity'] += item.quantity
                else:
                    combined_items[key] = {
                        'product_id': item.product_id,
                        'product': item.product,
                        'quantity': item.quantity,
                        'unit_price': item.unit_price
                    }

        if not combined_items:
            return APIResponse.error("No valid items found in the selected orders", 400)

        # Create a consolidated order
        order_number = f"CORD-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        consolidated = Order(
            order_number=order_number,
            requester_id=current_user.id,
            order_type='purchase',
            notes=notes,
            status='pending',
            is_dept_request=False
        )
        db.session.add(consolidated)
        db.session.flush()

        total = 0
        for v in combined_items.values():
            item = OrderItem(
                order_id=consolidated.id,
                product_id=v['product_id'],
                quantity=v['quantity'],
                unit_price=v['unit_price']
            )
            item.calculate_subtotal()
            total += item.subtotal
            db.session.add(item)

        consolidated.total_amount = total

        # Mark source dept orders as consolidated
        for oid in order_ids:
            o = Order.query.get(oid)
            if o:
                o.status = 'consolidated'

        db.session.commit()
        return APIResponse.success(
            data=consolidated.to_dict(),
            message=f"Consolidated {len(order_ids)} department orders into {order_number}",
            status_code=201
        )
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Dept consolidate error: {str(e)}")
        return APIResponse.server_error(str(e))


@bp.route('/api/dept-product-usage', methods=['GET', 'POST'])
@login_required
def api_dept_product_usage():
    """Get or record product usage for a department."""
    try:
        if request.method == 'GET':
            if current_user.role in ('admin', 'super_admin'):
                dept_ids = [d.id for d in Department.query.filter_by(org_user_id=current_user.id).all()]
                usages = DeptProductUsage.query.filter(
                    DeptProductUsage.department_id.in_(dept_ids)
                ).order_by(desc(DeptProductUsage.created_at)).limit(100).all()
            elif current_user.department_id:
                usages = DeptProductUsage.query.filter_by(
                    department_id=current_user.department_id
                ).order_by(desc(DeptProductUsage.created_at)).limit(100).all()
            else:
                usages = []
            return APIResponse.success(data=[u.to_dict() for u in usages], message="Usage records retrieved")

        elif request.method == 'POST':
            data = request.get_json()
            dept_id = current_user.department_id
            if not dept_id and current_user.role in ('admin', 'super_admin'):
                dept_id = data.get('dept_id')
            if not dept_id:
                return APIResponse.error("No department assigned", 400)

            product_name = data.get('product_name', '').strip()
            product_id = data.get('product_id')
            qty = data.get('quantity')
            if not qty or int(qty) < 1:
                return APIResponse.validation_error({'quantity': 'Quantity must be at least 1'})
            if not product_name and not product_id:
                return APIResponse.validation_error({'product_name': 'Product name or ID required'})

            usage = DeptProductUsage(
                department_id=dept_id,
                product_id=product_id or None,
                product_name=product_name or None,
                quantity=int(qty),
                unit=data.get('unit', 'unit'),
                recorded_by=current_user.id,
                notes=data.get('notes', '')
            )
            db.session.add(usage)
            db.session.commit()
            return APIResponse.success(data=usage.to_dict(), message="Usage recorded", status_code=201)
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Dept usage API error: {str(e)}")
        return APIResponse.server_error(str(e))


@bp.route('/api/org-members', methods=['GET'])
@login_required
def api_org_members():
    """List all users from the same organization (same organization_name, for admin only)."""
    try:
        if current_user.role not in ('admin', 'super_admin'):
            return APIResponse.forbidden("Only org admins can view member lists")
        members = User.query.filter_by(
            organization_name=current_user.organization_name
        ).filter(User.id != current_user.id).all()
        data = [{
            'id': m.id,
            'name': f"{m.first_name} {m.last_name}",
            'email': m.email,
            'role': m.role,
            'department_id': m.department_id,
        } for m in members]
        return APIResponse.success(data=data, message="Members retrieved")
    except Exception as e:
        return APIResponse.server_error(str(e))


@bp.route('/api/org-members/create', methods=['POST'])
@login_required
def api_org_members_create():
    """Org admin creates a new staff member under their organisation."""
    try:
        if current_user.role not in ('admin', 'super_admin'):
            return APIResponse.forbidden("Only org admins can create members")

        data = request.get_json()
        first_name = (data.get('first_name') or '').strip()
        last_name  = (data.get('last_name')  or '').strip()
        email      = (data.get('email')      or '').strip().lower()
        password   = data.get('password', '')
        dept_id    = data.get('department_id')

        if not first_name or not last_name:
            return APIResponse.validation_error({'name': 'First and last name are required'})
        if not email or '@' not in email:
            return APIResponse.validation_error({'email': 'Valid email is required'})
        if not password or len(password) < 8:
            return APIResponse.validation_error({'password': 'Password must be at least 8 characters'})

        if User.query.filter_by(email=email).first():
            return APIResponse.conflict("Email already registered")

        # Validate dept belongs to this admin if provided
        if dept_id:
            dept = Department.query.get(dept_id)
            if not dept or dept.org_user_id != current_user.id:
                return APIResponse.forbidden("Invalid department")

        member = User(
            first_name=first_name,
            last_name=last_name,
            email=email,
            password=password,
            phone=data.get('phone', ''),
            country=current_user.country,
            account_type=current_user.account_type,
            organization_name=current_user.organization_name,
        )
        member.role = 'staff'
        member.account_status = 'approved'  # Admin-created users are pre-approved
        if dept_id:
            member.department_id = int(dept_id)

        db.session.add(member)
        db.session.commit()

        return APIResponse.success(
            data={
                'id': member.id,
                'name': f"{member.first_name} {member.last_name}",
                'email': member.email,
                'role': member.role,
                'department_id': member.department_id,
            },
            message=f"Member {member.first_name} {member.last_name} created",
            status_code=201
        )
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Create member error: {str(e)}")
        return APIResponse.server_error(str(e))


# ── Inventory API for org users (hospital / laboratory / pharmacy) ──────────
@bp.route('/api/my-inventory')
@login_required
def api_my_inventory():
    """Products this user has ordered, annotated with quantity and stock levels."""
    try:
        # Only surface products this org has ever ordered (any status)
        user_orders = Order.query.filter_by(requester_id=current_user.id).all()

        ordered_qty = defaultdict(int)
        last_ordered = {}
        for order in user_orders:
            for item in (order.items or []):
                ordered_qty[item.product_id] += item.quantity
                prev = last_ordered.get(item.product_id)
                if prev is None or (order.created_at and order.created_at > prev):
                    last_ordered[item.product_id] = order.created_at

        if not ordered_qty:
            return APIResponse.success(data=[], message="No inventory yet — place your first order to track stock")

        products = Product.query.filter(Product.id.in_(list(ordered_qty.keys()))).all()
        result = []
        for p in products:
            stock = p.get_total_stock()
            if stock == 0:
                status = 'out_of_stock'
            elif stock <= p.reorder_level:
                status = 'low'
            else:
                status = 'in_stock'
            d = p.to_dict()
            d['current_stock'] = stock
            d['stock_status'] = status
            d['total_ordered'] = ordered_qty.get(p.id, 0)
            lo = last_ordered.get(p.id)
            d['last_ordered'] = lo.isoformat() if lo else None
            result.append(d)

        return APIResponse.success(data=result, message="Inventory retrieved")
    except Exception as e:
        current_app.logger.error(f"Inventory API error: {str(e)}")
        return APIResponse.server_error(str(e))

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
            
            if user and user.account_type == 'manufacturer' and user.check_password(password):
                status = getattr(user, 'account_status', 'approved')
                if status == 'pending':
                    return APIResponse.error(
                        "Your registration is under review. You will be notified once approved.", 403,
                        error_code="ACCOUNT_PENDING"
                    )
                if status == 'rejected':
                    reason = user.rejection_reason or "Please contact support for details."
                    return APIResponse.error(f"Your registration was not approved. {reason}", 403, error_code="ACCOUNT_REJECTED")
                if status == 'suspended':
                    return APIResponse.error("Your account has been suspended. Please contact support.", 403, error_code="ACCOUNT_SUSPENDED")

                login_user(user)

                manufacturer = Manufacturer.query.filter_by(user_id=user.id).first()
                if not manufacturer:
                    manufacturer = Manufacturer(
                        user_id=user.id,
                        legal_entity_name=user.organization_name or (user.first_name + ' ' + user.last_name),
                        verification_status='verified'
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
    """Redirect to unified registration — kept for backward compatibility"""
    return redirect(url_for('main.register'))


# ============ ADMIN ROUTES ============

@bp.route('/admin')
@bp.route('/admin/')
@login_required
@super_admin_required
def admin_dashboard():
    total = User.query.filter(User.role != 'super_admin').count()
    pending = User.query.filter_by(account_status='pending').filter(User.role != 'super_admin').count()
    approved = User.query.filter_by(account_status='approved').filter(User.role != 'super_admin').count()
    rejected = User.query.filter_by(account_status='rejected').filter(User.role != 'super_admin').count()
    recent = (User.query
              .filter(User.role != 'super_admin')
              .order_by(User.created_at.desc())
              .limit(10).all())
    return render_template('admin/dashboard.html',
                           total=total, pending=pending, approved=approved,
                           rejected=rejected, recent=recent)


@bp.route('/admin/registrations')
@login_required
@super_admin_required
def admin_registrations():
    status_filter = request.args.get('status', 'pending')
    query = User.query.filter(User.role != 'super_admin')
    if status_filter in ('pending', 'approved', 'rejected', 'suspended'):
        query = query.filter_by(account_status=status_filter)
    users = query.order_by(User.created_at.desc()).all()
    counts = {
        'pending': User.query.filter_by(account_status='pending').filter(User.role != 'super_admin').count(),
        'approved': User.query.filter_by(account_status='approved').filter(User.role != 'super_admin').count(),
        'rejected': User.query.filter_by(account_status='rejected').filter(User.role != 'super_admin').count(),
    }
    return render_template('admin/registrations.html',
                           users=users, status_filter=status_filter, counts=counts)


@bp.route('/admin/registrations/<int:user_id>/approve', methods=['POST'])
@login_required
@super_admin_required
def admin_approve_registration(user_id):
    user = User.query.get_or_404(user_id)
    user.account_status = 'approved'
    user.reviewed_by = current_user.id
    user.reviewed_at = datetime.utcnow()
    user.rejection_reason = None

    # Auto-create Manufacturer profile on approval
    if user.account_type == 'manufacturer':
        existing = Manufacturer.query.filter_by(user_id=user.id).first()
        if not existing:
            mfr = Manufacturer(
                user_id=user.id,
                legal_entity_name=user.organization_name or (user.first_name + ' ' + user.last_name),
                medical_license_number=user.license_number,
                business_address=user.business_address,
                verification_status='verified'
            )
            db.session.add(mfr)

    db.session.commit()
    current_app.logger.info(f"Admin {current_user.email} approved registration for {user.email}")
    flash(f"Registration approved for {user.organization_name or user.email}.", 'success')
    return redirect(url_for('main.admin_registrations', status='pending'))


@bp.route('/admin/registrations/<int:user_id>/reject', methods=['POST'])
@login_required
@super_admin_required
def admin_reject_registration(user_id):
    user = User.query.get_or_404(user_id)
    reason = request.form.get('reason', '').strip()
    user.account_status = 'rejected'
    user.reviewed_by = current_user.id
    user.reviewed_at = datetime.utcnow()
    user.rejection_reason = reason or None
    db.session.commit()
    current_app.logger.info(f"Admin {current_user.email} rejected registration for {user.email}")
    flash(f"Registration rejected for {user.organization_name or user.email}.", 'info')
    return redirect(url_for('main.admin_registrations', status='pending'))

@bp.route('/manufacturer/skus')
@login_required
def manufacturer_skus():
    """Manufacturer SKU inventory page"""
    manufacturer = get_current_manufacturer_profile()
    currency = manufacturer.currency if manufacturer else 'USD'
    currency_symbol = manufacturer.currency_symbol if manufacturer else '$'
    return render_template('manufacturer/sku-inventory.html',
                           manufacturer_currency=currency,
                           manufacturer_currency_symbol=currency_symbol)


@bp.route('/manufacturer/reports')
@login_required
def manufacturer_reports():
    """Manufacturer reporting page with period and status filters."""
    manufacturer = get_current_manufacturer_profile()
    if not manufacturer:
        flash('Manufacturer access required.', 'error')
        return redirect(url_for('main.manufacturer_login_page'))

    today = date.today()
    default_start = today - timedelta(days=29)
    start_date = parse_report_date(request.args.get('start_date'), default_start)
    end_date = parse_report_date(request.args.get('end_date'), today)
    if start_date > end_date:
        start_date, end_date = end_date, start_date

    status_filter = (request.args.get('status') or 'both').strip().lower()
    if status_filter not in {'both', 'active', 'inactive'}:
        status_filter = 'both'

    report = build_manufacturer_report(manufacturer, start_date, end_date, status_filter)

    return render_template(
        'manufacturer/reports.html',
        manufacturer=manufacturer,
        manufacturer_currency=manufacturer.currency,
        manufacturer_currency_symbol=manufacturer.currency_symbol,
        report=report,
        report_filters={
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat(),
            'status': status_filter,
        },
        manufacturer_page_title='Reports',
        manufacturer_primary_action_href=url_for('main.manufacturer_batch_register'),
        manufacturer_primary_action_label='Register Batch',
        manufacturer_primary_action_icon='add_circle'
    )


@bp.route('/manufacturer/requests')
@login_required
def manufacturer_requests():
    manufacturer = get_current_manufacturer_profile()
    if not manufacturer:
        flash('Manufacturer access required.', 'error')
        return redirect(url_for('main.manufacturer_login_page'))

    today = date.today()
    default_start = today - timedelta(days=29)
    start_date = parse_report_date(request.args.get('start_date'), default_start)
    end_date = parse_report_date(request.args.get('end_date'), today)
    if start_date > end_date:
        start_date, end_date = end_date, start_date

    status_filter = (request.args.get('status') or 'all').strip().lower()

    # Query grouped DistributorRequest records (not individual demands)
    query = DistributorRequest.query.filter_by(manufacturer_id=manufacturer.id)
    if status_filter != 'all':
        query = query.filter_by(status=status_filter)

    start_dt = datetime.combine(start_date, datetime.min.time())
    end_dt = datetime.combine(end_date + timedelta(days=1), datetime.min.time())
    query = query.filter(DistributorRequest.requested_at >= start_dt, DistributorRequest.requested_at < end_dt)

    requests_list = query.order_by(desc(DistributorRequest.requested_at)).all()

    summary = {
        'total_count': len(requests_list),
        'pending_count': sum(1 for r in requests_list if r.status in {'pending', 'approved', 'payment_validated'}),
        'completed_count': sum(1 for r in requests_list if r.status in {'supplied', 'completed'}),
        'rejected_count': sum(1 for r in requests_list if r.status == 'rejected'),
        'total_amount': sum(r.total_amount or 0 for r in requests_list),
        'total_items': sum(r.item_count or 0 for r in requests_list),
    }

    return render_template(
        'manufacturer/requests.html',
        manufacturer=manufacturer,
        manufacturer_currency=manufacturer.currency,
        manufacturer_currency_symbol=manufacturer.currency_symbol,
        demands=requests_list,
        request_summary=summary,
        request_filters={
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat(),
            'status': status_filter,
        },
        manufacturer_page_title='Requests',
        manufacturer_primary_action_href=url_for('main.manufacturer_reports'),
        manufacturer_primary_action_label='View Reports',
        manufacturer_primary_action_icon='assessment'
    )


@bp.route('/manufacturer/requests/<int:demand_id>/approve', methods=['POST'])
@login_required
def manufacturer_approve_request(demand_id):
    manufacturer = get_current_manufacturer_profile()
    if not manufacturer:
        flash('Manufacturer access required.', 'error')
        return redirect(url_for('main.manufacturer_login_page'))

    demand = DistributorDemand.query.filter_by(id=demand_id, manufacturer_id=manufacturer.id).first()
    if not demand:
        flash('Demand request not found.', 'error')
        return redirect(url_for('main.manufacturer_requests'))

    try:
        approved_quantity = int(request.form.get('approved_quantity', demand.requested_quantity) or demand.requested_quantity)
    except (TypeError, ValueError):
        flash('Approved quantity must be a valid number.', 'error')
        return redirect(url_for('main.manufacturer_requests'))

    available_quantity = demand.product_sku.get_total_stock() if demand.product_sku else 0
    if approved_quantity <= 0:
        flash('Approved quantity must be greater than zero.', 'error')
        return redirect(url_for('main.manufacturer_requests'))
    if approved_quantity > available_quantity:
        flash(f'Only {available_quantity} active units are available for approval.', 'error')
        return redirect(url_for('main.manufacturer_requests'))
    if demand.payment_status != 'validated':
        flash('Payment must be validated before approval.', 'error')
        return redirect(url_for('main.manufacturer_requests'))

    demand.approved_quantity = approved_quantity
    demand.manufacturer_note = (request.form.get('manufacturer_note') or '').strip() or demand.manufacturer_note
    demand.status = 'approved'
    demand.approved_at = datetime.utcnow()
    demand.recalculate_total()
    db.session.commit()

    flash(f'Demand {demand.demand_number} approved for {approved_quantity} units.', 'success')
    return redirect(url_for('main.manufacturer_requests'))


@bp.route('/manufacturer/requests/<int:demand_id>/reject', methods=['POST'])
@login_required
def manufacturer_reject_request(demand_id):
    manufacturer = get_current_manufacturer_profile()
    if not manufacturer:
        flash('Manufacturer access required.', 'error')
        return redirect(url_for('main.manufacturer_login_page'))

    demand = DistributorDemand.query.filter_by(id=demand_id, manufacturer_id=manufacturer.id).first()
    if not demand:
        flash('Demand request not found.', 'error')
        return redirect(url_for('main.manufacturer_requests'))

    demand.status = 'rejected'
    demand.manufacturer_note = (request.form.get('manufacturer_note') or '').strip() or 'Request not approved.'
    db.session.commit()

    flash(f'Demand {demand.demand_number} was rejected.', 'info')
    return redirect(url_for('main.manufacturer_requests'))


@bp.route('/manufacturer/requests/<int:demand_id>/supply', methods=['POST'])
@login_required
def manufacturer_supply_request(demand_id):
    manufacturer = get_current_manufacturer_profile()
    if not manufacturer:
        flash('Manufacturer access required.', 'error')
        return redirect(url_for('main.manufacturer_login_page'))

    demand = DistributorDemand.query.filter_by(id=demand_id, manufacturer_id=manufacturer.id).first()
    if not demand:
        flash('Demand request not found.', 'error')
        return redirect(url_for('main.manufacturer_requests'))

    try:
        if demand.status not in {'pending', 'approved', 'payment_validated'}:
            raise ValueError('Only pending, approved, or payment-validated requests can be supplied.')
        if demand.payment_status != 'validated':
            raise ValueError('Payment must be validated before supply.')

        if not demand.approved_quantity:
            demand.approved_quantity = demand.requested_quantity
            demand.approved_at = datetime.utcnow()
            demand.status = 'approved'

        supplied_quantity = fulfill_distributor_demand(demand, current_user.id)
        db.session.commit()
        flash(f'Demand {demand.demand_number} supplied with {supplied_quantity} units.', 'success')
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), 'error')
    except Exception as exc:
        db.session.rollback()
        current_app.logger.error(f'Manufacturer supply error: {str(exc)}', exc_info=True)
        flash('Unable to supply this request right now.', 'error')

    return redirect(url_for('main.manufacturer_requests'))


@bp.route('/manufacturer/skus/<int:product_id>')
@login_required
def manufacturer_sku_detail(product_id):
    """Manufacturer product detail page"""
    manufacturer = get_current_manufacturer_profile()
    if not manufacturer:
        flash('Manufacturer access required.', 'error')
        return redirect(url_for('main.manufacturer_skus'))

    product = get_manufacturer_product(manufacturer.id, product_id)
    if not product:
        flash('Product not found.', 'error')
        return redirect(url_for('main.manufacturer_skus'))

    return render_template('manufacturer/sku-detail.html', product_id=product.id,
                           manufacturer_currency=manufacturer.currency,
                           manufacturer_currency_symbol=manufacturer.currency_symbol)

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

@bp.route('/api/distributor/catalog')
@login_required
def api_distributor_catalog():
    """Get manufacturer catalog products available to distributors."""
    distributor = get_distributor_user_or_none()
    if not distributor:
        return APIResponse.forbidden('Distributor access required')

    products = ProductSKU.query.join(Manufacturer, ProductSKU.manufacturer_id == Manufacturer.id).order_by(ProductSKU.created_at.desc()).all()
    data = []
    for product in products:
        if product.status != 'active':
            continue
        total_stock = product.get_total_stock()
        data.append({
            'id': product.id,
            'name': product.name,
            'sku': product.sku,
            'category': product.category,
            'description': product.description,
            'status': product.status,
            'unit_price': product.unit_price or 0,
            'available_quantity': total_stock,
            'manufacturer_id': product.manufacturer_id,
            'manufacturer_name': product.manufacturer.legal_entity_name if product.manufacturer else None,
            'manufacturer_currency_symbol': product.manufacturer.currency_symbol if product.manufacturer else '$',
        })
    # Also return ALL manufacturers so the filter dropdown shows them even if they have 0 products
    all_manufacturers = Manufacturer.query.order_by(Manufacturer.legal_entity_name.asc()).all()
    return APIResponse.success(
        data={
            'products': data,
            'manufacturers': [{
                'id': m.id,
                'name': m.legal_entity_name,
                'currency_symbol': m.currency_symbol,
            } for m in all_manufacturers],
        },
        message='Distributor catalog retrieved'
    )


@bp.route('/api/distributor/demands', methods=['GET', 'POST'])
@login_required
def api_distributor_demands():
    """Create and list distributor demands against manufacturer catalog products."""
    distributor = get_distributor_user_or_none()
    if not distributor:
        return APIResponse.forbidden('Distributor access required')

    if request.method == 'GET':
        start_date_raw = request.args.get('start_date')
        end_date_raw = request.args.get('end_date')
        status = (request.args.get('status') or 'all').strip().lower()

        query = DistributorDemand.query.filter_by(distributor_user_id=distributor.id)
        if status in {'pending', 'approved', 'payment_validated', 'supplied', 'completed', 'rejected'}:
            query = query.filter_by(status=status)

        if start_date_raw:
            try:
                start_date = datetime.strptime(start_date_raw, '%Y-%m-%d')
                query = query.filter(DistributorDemand.created_at >= start_date)
            except ValueError:
                pass
        if end_date_raw:
            try:
                end_date = datetime.strptime(end_date_raw, '%Y-%m-%d') + timedelta(days=1)
                query = query.filter(DistributorDemand.created_at < end_date)
            except ValueError:
                pass

        demands = query.order_by(desc(DistributorDemand.created_at)).all()
        total_worth = sum(item.total_amount or 0 for item in demands)
        total_units = sum(item.requested_quantity or 0 for item in demands)
        return APIResponse.success(
            data={
                'items': [item.to_dict() for item in demands],
                'summary': {
                    'count': len(demands),
                    'total_worth': total_worth,
                    'total_units': total_units,
                    'pending': len([d for d in demands if d.status == 'pending']),
                    'completed': len([d for d in demands if d.status in {'supplied', 'completed'}]),
                }
            },
            message='Distributor demands retrieved'
        )

    data = request.get_json() or {}
    try:
        product_sku_id = int(data.get('product_sku_id'))
        quantity = int(data.get('requested_quantity'))
    except (TypeError, ValueError):
        return APIResponse.validation_error({'requested_quantity': 'Product and quantity must be valid numbers'})

    if quantity <= 0:
        return APIResponse.validation_error({'requested_quantity': 'Requested quantity must be greater than zero'})

    product = ProductSKU.query.get(product_sku_id)
    if not product or product.status != 'active':
        return APIResponse.not_found('Product')

    demand = DistributorDemand(
        demand_number=generate_demand_number(),
        distributor_user_id=distributor.id,
        manufacturer_id=product.manufacturer_id,
        product_sku_id=product.id,
        requested_quantity=quantity,
        approved_quantity=0,
        supplied_quantity=0,
        unit_price=product.unit_price or 0,
        status='pending',
        notes=(data.get('notes') or '').strip() or None,
    )
    demand.recalculate_total()
    db.session.add(demand)
    db.session.commit()
    return APIResponse.success(data=demand.to_dict(), message='Demand created successfully', status_code=201)


@bp.route('/api/distributor/demands/<int:demand_id>/payment-validate', methods=['POST'])
@login_required
def api_distributor_validate_payment(demand_id):
    """Distributor marks demand payment as validated for manufacturer to process."""
    distributor = get_distributor_user_or_none()
    if not distributor:
        return APIResponse.forbidden('Distributor access required')

    demand = DistributorDemand.query.get(demand_id)
    if not demand or demand.distributor_user_id != distributor.id:
        return APIResponse.not_found('Demand')

    if demand.status not in {'pending', 'approved'}:
        return APIResponse.validation_error({'status': 'Payment can only be validated for pending or approved demands'})

    demand.payment_status = 'validated'
    demand.status = 'payment_validated'
    db.session.commit()
    return APIResponse.success(data=demand.to_dict(), message='Payment validated successfully')


@bp.route('/api/manufacturer/requests')
@login_required
def api_manufacturer_requests():
    """Get manufacturer-scoped demands raised by distributors."""
    manufacturer = get_current_manufacturer_profile()
    if not manufacturer:
        return APIResponse.forbidden('Manufacturer access required')

    start_date_raw = request.args.get('start_date')
    end_date_raw = request.args.get('end_date')
    status = (request.args.get('status') or 'all').strip().lower()

    query = DistributorDemand.query.filter_by(manufacturer_id=manufacturer.id)
    if status in {'pending', 'approved', 'payment_validated', 'supplied', 'completed', 'rejected'}:
        query = query.filter_by(status=status)

    if start_date_raw:
        try:
            start_date = datetime.strptime(start_date_raw, '%Y-%m-%d')
            query = query.filter(DistributorDemand.created_at >= start_date)
        except ValueError:
            pass
    if end_date_raw:
        try:
            end_date = datetime.strptime(end_date_raw, '%Y-%m-%d') + timedelta(days=1)
            query = query.filter(DistributorDemand.created_at < end_date)
        except ValueError:
            pass

    demands = query.order_by(desc(DistributorDemand.created_at)).all()
    total_worth = sum(item.total_amount or 0 for item in demands)
    total_units = sum(item.requested_quantity or 0 for item in demands)

    return APIResponse.success(
        data={
            'items': [item.to_dict() for item in demands],
            'summary': {
                'count': len(demands),
                'total_worth': total_worth,
                'total_units': total_units,
                'pending': len([d for d in demands if d.status in {'pending', 'payment_validated'}]),
                'completed': len([d for d in demands if d.status in {'supplied', 'completed'}]),
            }
        },
        message='Manufacturer requests retrieved'
    )


@bp.route('/api/manufacturer/requests/<int:demand_id>/approve', methods=['POST'])
@login_required
def api_manufacturer_approve_request(demand_id):
    """Approve distributor demand quantity from manufacturer side."""
    manufacturer = get_current_manufacturer_profile()
    if not manufacturer:
        return APIResponse.forbidden('Manufacturer access required')

    demand = DistributorDemand.query.get(demand_id)
    if not demand or demand.manufacturer_id != manufacturer.id:
        return APIResponse.not_found('Demand')

    data = request.get_json() or {}
    try:
        approved_quantity = int(data.get('approved_quantity', demand.requested_quantity))
    except (TypeError, ValueError):
        return APIResponse.validation_error({'approved_quantity': 'Approved quantity must be a valid number'})

    if approved_quantity <= 0:
        return APIResponse.validation_error({'approved_quantity': 'Approved quantity must be greater than zero'})

    product = ProductSKU.query.get(demand.product_sku_id)
    if not product:
        return APIResponse.not_found('Product')

    if approved_quantity > product.get_total_stock():
        return APIResponse.validation_error({'approved_quantity': 'Approved quantity exceeds available stock'})

    demand.approved_quantity = approved_quantity
    demand.unit_price = product.unit_price or 0
    demand.recalculate_total()
    demand.status = 'approved'
    demand.approved_at = datetime.utcnow()
    db.session.commit()
    return APIResponse.success(data=demand.to_dict(), message='Demand approved successfully')


@bp.route('/api/manufacturer/requests/<int:demand_id>/supply', methods=['POST'])
@login_required
def api_manufacturer_supply_request(demand_id):
    """Supply approved demand, deducting manufacturer stock and crediting distributor inventory."""
    manufacturer = get_current_manufacturer_profile()
    if not manufacturer:
        return APIResponse.forbidden('Manufacturer access required')

    demand = DistributorDemand.query.get(demand_id)
    if not demand or demand.manufacturer_id != manufacturer.id:
        return APIResponse.not_found('Demand')

    if demand.payment_status != 'validated':
        return APIResponse.validation_error({'payment': 'Payment must be validated before supply'})

    if demand.status not in {'approved', 'payment_validated'}:
        return APIResponse.validation_error({'status': 'Only approved or payment-validated demands can be supplied'})

    supply_qty = demand.approved_quantity or demand.requested_quantity
    if supply_qty <= 0:
        return APIResponse.validation_error({'approved_quantity': 'Supply quantity is invalid'})

    try:
        allocations = allocate_supply_from_batches(demand.product_sku_id, supply_qty)
    except ValueError as exc:
        return APIResponse.validation_error({'quantity': str(exc)})

    inventory = DistributorInventory.query.filter_by(
        distributor_user_id=demand.distributor_user_id,
        manufacturer_id=demand.manufacturer_id,
        product_sku_id=demand.product_sku_id,
    ).first()
    if not inventory:
        inventory = DistributorInventory(
            distributor_user_id=demand.distributor_user_id,
            manufacturer_id=demand.manufacturer_id,
            product_sku_id=demand.product_sku_id,
            quantity=0,
        )
        db.session.add(inventory)

    inventory.quantity = (inventory.quantity or 0) + supply_qty
    demand.supplied_quantity = supply_qty
    demand.status = 'supplied'
    demand.supplied_at = datetime.utcnow()

    tx = Transaction(
        manufacturer_id=manufacturer.id,
        transaction_id=f"SUP-{datetime.now().strftime('%Y%m%d%H%M%S')}-{demand.id}",
        service_type='demand_supply',
        amount=demand.total_amount or demand.recalculate_total(),
        batch_volume=supply_qty,
        status='completed',
    )
    db.session.add(tx)
    db.session.commit()

    return APIResponse.success(
        data={
            'demand': demand.to_dict(),
            'inventory': inventory.to_dict(),
            'allocations': allocations,
        },
        message='Demand supplied successfully'
    )


@bp.route('/api/distributor/inventory')
@login_required
def api_distributor_inventory():
    """Get distributor inventory accumulated from supplied demands."""
    distributor = get_distributor_user_or_none()
    if not distributor:
        return APIResponse.forbidden('Distributor access required')

    items = DistributorInventory.query.filter_by(distributor_user_id=distributor.id).order_by(desc(DistributorInventory.updated_at)).all()
    total_units = sum(item.quantity or 0 for item in items)
    total_worth = sum(((item.quantity or 0) * (((item.product_sku.unit_price if item.product_sku else 0) or 0)) for item in items))

    return APIResponse.success(
        data={
            'items': [item.to_dict() for item in items],
            'summary': {
                'count': len(items),
                'total_units': total_units,
                'total_worth': total_worth,
            }
        },
        message='Distributor inventory retrieved'
    )


@bp.route('/api/distributor/inventory/<int:inventory_id>/price', methods=['PUT'])
@login_required
def api_distributor_update_selling_price(inventory_id):
    """Distributor sets or updates the selling price for an inventory item."""
    distributor = get_distributor_user_or_none()
    if not distributor:
        return APIResponse.forbidden('Distributor access required')

    item = DistributorInventory.query.filter_by(id=inventory_id, distributor_user_id=distributor.id).first()
    if not item:
        return APIResponse.not_found('Inventory item')

    data = request.get_json() or {}
    try:
        new_price = float(data.get('selling_price', 0) or 0)
    except (TypeError, ValueError):
        return APIResponse.validation_error({'selling_price': 'Selling price must be a valid number'})

    if new_price < 0:
        return APIResponse.validation_error({'selling_price': 'Selling price cannot be negative'})

    pricing = DistributorSellingPrice.query.filter_by(
        distributor_user_id=distributor.id,
        manufacturer_id=item.manufacturer_id,
        product_sku_id=item.product_sku_id,
    ).first()
    if not pricing:
        pricing = DistributorSellingPrice(
            distributor_user_id=distributor.id,
            manufacturer_id=item.manufacturer_id,
            product_sku_id=item.product_sku_id,
            selling_price=new_price,
        )
        db.session.add(pricing)
    else:
        pricing.selling_price = new_price
    db.session.commit()

    cost = (item.product_sku.unit_price if item.product_sku else 0) or 0
    profit_per_unit = round(new_price - cost, 4)
    total_profit = round(profit_per_unit * (item.quantity or 0), 2)
    return APIResponse.success(
        data={
            'id': item.id,
            'selling_price': new_price,
            'cost_price': cost,
            'profit_per_unit': profit_per_unit,
            'total_profit': total_profit,
        },
        message='Selling price updated'
    )


# ============ MANUFACTURER API ROUTES ============

@bp.route('/api/manufacturer/skus', methods=['GET', 'POST'])
@login_required
def api_manufacturer_skus():
    """Get or create SKUs for the current manufacturer"""
    try:
        if current_user.account_type != 'manufacturer':
            return APIResponse.forbidden("Manufacturer access required")

        manufacturer = get_current_manufacturer_profile()
        if not manufacturer:
            if request.method == 'GET':
                return APIResponse.success(data=[], message="No manufacturer profile found")
            return APIResponse.error("Manufacturer profile not found", 400)

        if request.method == 'GET':
            products = ProductSKU.query.filter_by(manufacturer_id=manufacturer.id).order_by(desc(ProductSKU.created_at)).all()
            return APIResponse.success(
                data=[serialize_manufacturer_product(p) for p in products],
                message="SKUs retrieved"
            )

        data = request.get_json() or {}
        name = (data.get('name') or '').strip()
        sku = normalize_sku(data.get('sku'))
        category = (data.get('category') or '').strip() or None
        description = (data.get('description') or '').strip() or None
        status = (data.get('status') or 'pending').strip().lower()

        if not name:
            return APIResponse.error("Product name is required", 400)
        if not sku:
            return APIResponse.error("SKU is required", 400)
        if status not in {'active', 'pending', 'inactive'}:
            return APIResponse.error("Invalid product status", 400)

        try:
            unit_price = float(data.get('unit_price', 0) or 0)
            reorder_level = int(data.get('reorder_level', 0) or 0)
        except (TypeError, ValueError):
            return APIResponse.error("Unit price and reorder level must be valid numbers", 400)

        if unit_price < 0:
            return APIResponse.error("Unit price cannot be negative", 400)
        if reorder_level < 0:
            return APIResponse.error("Reorder level cannot be negative", 400)

        existing_product = ProductSKU.query.filter(func.lower(ProductSKU.sku) == sku.lower()).first()
        if existing_product:
            if existing_product.manufacturer_id == manufacturer.id:
                return APIResponse.conflict("A product with this SKU already exists in your catalog")
            return APIResponse.conflict("This SKU is already in use. Choose a unique SKU")

        product = ProductSKU(
            manufacturer_id=manufacturer.id,
            name=name,
            sku=sku,
            category=category,
            description=description,
            unit_price=unit_price,
            reorder_level=reorder_level,
            status=status
        )
        db.session.add(product)
        db.session.commit()

        return APIResponse.success(
            data=product.to_dict(),
            message="Product created successfully",
            status_code=201
        )
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"SKU API error: {str(e)}")
        if request.method == 'GET':
            return APIResponse.success(data=[], message="No products found")
        return APIResponse.server_error("Could not save product")


@bp.route('/api/manufacturer/skus/<int:product_id>', methods=['GET', 'PUT'])
@login_required
def api_manufacturer_sku_detail(product_id):
    """Get or update a single manufacturer product."""
    try:
        manufacturer = get_current_manufacturer_profile()
        if not manufacturer:
            return APIResponse.forbidden("Manufacturer access required")

        product = get_manufacturer_product(manufacturer.id, product_id)
        if not product:
            return APIResponse.not_found("Product")

        if request.method == 'GET':
            return APIResponse.success(
                data=serialize_manufacturer_product(product),
                message="Product retrieved"
            )

        data = request.get_json() or {}
        if 'unit_price' not in data:
            return APIResponse.validation_error({'unit_price': 'Unit price is required'})

        try:
            unit_price = float(data.get('unit_price', 0) or 0)
        except (TypeError, ValueError):
            return APIResponse.validation_error({'unit_price': 'Unit price must be a valid number'})

        if unit_price < 0:
            return APIResponse.validation_error({'unit_price': 'Unit price cannot be negative'})

        status = (data.get('status') or product.status or 'pending').strip().lower()
        if status not in {'active', 'pending', 'inactive'}:
            return APIResponse.validation_error({'status': 'Status must be active, pending, or inactive'})

        product.unit_price = unit_price
        product.status = status
        db.session.commit()

        return APIResponse.success(
            data=serialize_manufacturer_product(product),
            message="Product updated successfully"
        )
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Manufacturer product detail API error: {str(e)}")
        return APIResponse.server_error("Could not update product")

@bp.route('/api/manufacturer/profile')
@login_required
def api_manufacturer_profile():
    """Return current manufacturer's profile including currency."""
    try:
        manufacturer = get_current_manufacturer_profile()
        if not manufacturer:
            return APIResponse.not_found("Manufacturer profile not found")
        return APIResponse.success(data=manufacturer.to_dict(), message="Profile retrieved")
    except Exception as e:
        current_app.logger.error(f"Manufacturer profile API error: {str(e)}")
        return APIResponse.server_error("Could not retrieve profile")

@bp.route('/api/manufacturer/currency', methods=['PUT'])
@login_required
def api_manufacturer_currency():
    """Update the manufacturer's preferred currency (ISO 4217 code)."""
    try:
        manufacturer = get_current_manufacturer_profile()
        if not manufacturer:
            return APIResponse.not_found("Manufacturer profile not found")

        data = request.get_json() or {}
        currency = (data.get('currency') or '').strip().upper()

        # Basic ISO-4217 sanity check: 3 uppercase letters
        import re as _re
        if not currency or not _re.match(r'^[A-Z]{3}$', currency):
            return APIResponse.validation_error({'currency': 'A valid 3-letter ISO 4217 currency code is required (e.g. USD, NGN, EUR)'})

        manufacturer.currency = currency
        db.session.commit()

        return APIResponse.success(
            data={'currency': manufacturer.currency, 'currency_symbol': manufacturer.currency_symbol},
            message="Currency updated successfully"
        )
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Manufacturer currency update error: {str(e)}")
        return APIResponse.server_error("Could not update currency")

@bp.route('/api/manufacturer/stats')
@login_required
def api_manufacturer_stats():
    """Get manufacturer statistics"""
    try:
        manufacturer = get_current_manufacturer_profile()
        if not manufacturer:
            return APIResponse.success(data={
                'total_skus': 0,
                'active_skus': 0,
                'pending_skus': 0,
                'total_batches': 0,
                'active_batches': 0,
                'total_units': 0
            }, message="No manufacturer profile")
        
        products = ProductSKU.query.filter_by(manufacturer_id=manufacturer.id).all()
        batches = get_manufacturer_batches(manufacturer.id)
        
        total_skus = len(products)
        active_skus = len([p for p in products if p.status == 'active'])
        pending_skus = len([p for p in products if p.status == 'pending'])
        total_batches = len(batches)
        active_batches = len([b for b in batches if b.status == 'active'])
        total_units = sum(b.quantity for b in batches)
        
        return APIResponse.success(data={
            'total_skus': total_skus,
            'active_skus': active_skus,
            'pending_skus': pending_skus,
            'total_batches': total_batches,
            'active_batches': active_batches,
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
        manufacturer = get_current_manufacturer_profile()
        if not manufacturer:
            return APIResponse.success(data=[], message="No manufacturer profile")
        
        batches = get_manufacturer_batches(manufacturer.id)
        
        return APIResponse.success(
            data=[b.to_dict() for b in batches],
            message="Batches retrieved"
        )
    except Exception as e:
        current_app.logger.error(f"Batches API error: {str(e)}")
        return APIResponse.success(data=[], message="No batches found")


@bp.route('/api/manufacturer/batches/<int:batch_id>/status', methods=['PUT'])
@login_required
def api_manufacturer_batch_status(batch_id):
    """Activate or deactivate a manufacturer-owned batch."""
    try:
        manufacturer = get_current_manufacturer_profile()
        if not manufacturer:
            return APIResponse.not_found("Manufacturer profile")

        batch = Batch.query.get(batch_id)
        if not batch or not batch_belongs_to_manufacturer(batch, manufacturer.id):
            return APIResponse.not_found("Batch")

        data = request.get_json() or {}
        status = (data.get('status') or '').strip().lower()
        if status not in {'active', 'inactive'}:
            return APIResponse.validation_error({'status': 'Status must be active or inactive'})

        batch.status = status
        db.session.commit()

        product = batch.product_sku
        refreshed_batches = get_manufacturer_product_batches(product)
        return APIResponse.success(
            data={
                'batch': batch.to_dict(),
                'product': serialize_manufacturer_product(product),
                'batches': [item.to_dict() for item in refreshed_batches],
            },
            message=f"Batch {status} successfully"
        )
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Manufacturer batch status update error: {str(e)}")
        return APIResponse.server_error("Could not update batch status")

@bp.route('/api/manufacturer/batch/register', methods=['POST'])
@login_required
def api_manufacturer_batch_register():
    """Register a new batch"""
    try:
        data = request.get_json()
        
        manufacturer = get_current_manufacturer_profile()
        if not manufacturer:
            return APIResponse.error("Manufacturer profile not found", 400)
        
        try:
            product_id = int(data.get('product_id'))
            quantity = int(data.get('quantity', 0) or 0)
        except (TypeError, ValueError):
            return APIResponse.error("Product and quantity must be valid numbers", 400)

        if quantity <= 0:
            return APIResponse.error("Quantity must be greater than zero", 400)

        product = get_manufacturer_product(manufacturer.id, product_id)
        if not product:
            return APIResponse.error("Product not found", 404)

        manufacturing_date = datetime.strptime(data.get('manufacturing_date'), '%Y-%m-%d').date() if data.get('manufacturing_date') else None
        expiry_date = datetime.strptime(data.get('expiry_date'), '%Y-%m-%d').date() if data.get('expiry_date') else None

        if manufacturing_date and expiry_date and expiry_date <= manufacturing_date:
            return APIResponse.error("Expiry date must be after manufacturing date", 400)

        batch_number = f"{product.sku[:24]}-{manufacturer.id}-{datetime.now().strftime('%y%m%d%H%M%S')}"
        qr_code = f"https://steryl.com/verify/{batch_number}"
        
        batch = Batch(
            product_id=None,
            product_sku_id=product.id,
            batch_number=batch_number,
            quantity=quantity,
            manufacturing_date=manufacturing_date,
            expiry_date=expiry_date,
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
        manufacturer = get_current_manufacturer_profile()
        if not manufacturer:
            return APIResponse.success(data=[], message="No manufacturer profile")
        
        batches = get_manufacturer_batches(manufacturer.id)
        
        queue_items = []
        for batch in batches:
            print_item = PrintQueue.query.filter_by(batch_id=batch.id).first()
            if print_item:
                queue_items.append({
                    'id': print_item.id,
                    'batch_id': batch.id,
                    'batch_number': batch.batch_number,
                    'product_name': batch.product_sku.name if batch.product_sku else (batch.product.name if batch.product else None),
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
                    'product_name': batch.product_sku.name if batch.product_sku else (batch.product.name if batch.product else None),
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
        manufacturer = get_current_manufacturer_profile()
        if not manufacturer:
            return APIResponse.forbidden("Manufacturer access required")

        print_item = PrintQueue.query.get_or_404(queue_id)
        batch = Batch.query.get(print_item.batch_id)
        if not batch_belongs_to_manufacturer(batch, manufacturer.id):
            return APIResponse.forbidden("You cannot access this label")
        
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
        manufacturer = get_current_manufacturer_profile()
        if not manufacturer:
            return APIResponse.forbidden("Manufacturer access required")

        print_item = PrintQueue.query.get_or_404(queue_id)
        batch = Batch.query.get(print_item.batch_id)
        if not batch_belongs_to_manufacturer(batch, manufacturer.id):
            return APIResponse.forbidden("You cannot update this label")

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
        manufacturer = get_current_manufacturer_profile()
        if not manufacturer:
            return APIResponse.forbidden("Manufacturer access required")

        batches = get_manufacturer_batches(manufacturer.id)
        batch_ids = [batch.id for batch in batches]
        pending_items = PrintQueue.query.filter(PrintQueue.batch_id.in_(batch_ids), PrintQueue.status == 'pending').all() if batch_ids else []
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

@bp.route('/api/manufacturer/notifications')
@login_required
def api_manufacturer_notifications():
    """Get manufacturer-scoped notifications for the current user."""
    try:
        manufacturer = get_current_manufacturer_profile()
        if not manufacturer:
            return APIResponse.success(data={'items': [], 'unread_count': 0, 'summary': {}}, message="No manufacturer profile")

        return APIResponse.success(
            data=serialize_manufacturer_notifications(manufacturer),
            message="Notifications retrieved"
        )
    except Exception as e:
        current_app.logger.error(f"Manufacturer notifications error: {str(e)}")
        return APIResponse.success(data={'items': [], 'unread_count': 0, 'summary': {}}, message="No notifications found")


@bp.route('/api/manufacturer/notifications/read', methods=['POST'])
@login_required
def api_manufacturer_notifications_mark_read():
    """Mark a single manufacturer notification as read for the current user."""
    try:
        manufacturer = get_current_manufacturer_profile()
        if not manufacturer:
            return APIResponse.forbidden("Manufacturer access required")

        data = request.get_json() or {}
        notification_id = (data.get('notification_id') or '').strip()
        signature = (data.get('signature') or '').strip()

        if not notification_id or not signature:
            return APIResponse.validation_error({'notification_id': 'Notification id and signature are required'})

        notification = next(
            (item for item in build_manufacturer_notifications(manufacturer) if item['id'] == notification_id),
            None
        )
        if not notification:
            return APIResponse.not_found('Notification')

        expected_signature = build_manufacturer_notification_signature(notification)
        if signature != expected_signature:
            return APIResponse.conflict('Notification content changed. Refresh and review the latest alert.')

        upsert_manufacturer_notification_state(manufacturer.id, notification_id, expected_signature)
        db.session.commit()

        return APIResponse.success(
            data=serialize_manufacturer_notifications(manufacturer),
            message='Notification marked as read'
        )
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Manufacturer notification mark-read error: {str(e)}")
        return APIResponse.server_error(str(e))


@bp.route('/api/manufacturer/notifications/read-all', methods=['POST'])
@login_required
def api_manufacturer_notifications_mark_all_read():
    """Mark all current manufacturer notifications as read for the current user."""
    try:
        manufacturer = get_current_manufacturer_profile()
        if not manufacturer:
            return APIResponse.forbidden("Manufacturer access required")

        notifications = build_manufacturer_notifications(manufacturer)
        for notification in notifications:
            upsert_manufacturer_notification_state(
                manufacturer.id,
                notification['id'],
                build_manufacturer_notification_signature(notification)
            )

        db.session.commit()

        return APIResponse.success(
            data=serialize_manufacturer_notifications(manufacturer),
            message='Notifications marked as read'
        )
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Manufacturer notification mark-all-read error: {str(e)}")
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
    try:
        uid = current_user.id

        # Pending and active orders for THIS user only
        pending_orders = Order.query.filter_by(
            requester_id=uid, status='pending'
        ).count()
        active_orders = Order.query.filter(
            Order.requester_id == uid,
            Order.status.in_(['pending', 'approved'])
        ).count()

        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        sixty_days_ago = datetime.utcnow() - timedelta(days=60)

        monthly_spend = db.session.query(func.sum(Order.total_amount)).filter(
            Order.requester_id == uid,
            Order.created_at >= thirty_days_ago,
            Order.status == 'approved'
        ).scalar() or 0

        # Inventory health: based on products this user has ever ordered
        ordered_ids = db.session.query(OrderItem.product_id).join(Order).filter(
            Order.requester_id == uid
        ).distinct().all()
        ordered_ids = [r[0] for r in ordered_ids]

        if ordered_ids:
            products = Product.query.filter(Product.id.in_(ordered_ids)).all()
            total_products = len(products)
            low_stock_count = sum(1 for p in products if p.get_total_stock() <= p.reorder_level)
            inventory_health = round(
                ((total_products - low_stock_count) / total_products * 100)
                if total_products > 0 else 100, 1
            )
        else:
            inventory_health = 100.0  # No orders yet → nothing to alert on

        # Health trend: rejected orders this user had vs prior period
        prev_low = db.session.query(func.count(Order.id)).filter(
            Order.requester_id == uid,
            Order.created_at >= sixty_days_ago,
            Order.created_at < thirty_days_ago,
            Order.status == 'rejected'
        ).scalar() or 0
        curr_low = db.session.query(func.count(Order.id)).filter(
            Order.requester_id == uid,
            Order.created_at >= thirty_days_ago,
            Order.status == 'rejected'
        ).scalar() or 0
        health_change = round(float(prev_low - curr_low), 1)

        return APIResponse.success(
            data={
                'inventory_health': inventory_health,
                'pending_approvals': pending_orders,
                'monthly_spend': float(monthly_spend),
                'active_orders': active_orders,
                'inventory_health_change': health_change
            },
            message="Dashboard stats retrieved"
        )
    except Exception as e:
        current_app.logger.error(f"Dashboard stats error: {str(e)}")
        return APIResponse.server_error(str(e))


@bp.route('/api/recent-activity')
@login_required
def api_recent_activity():
    try:
        recent_orders = (
            Order.query
            .filter_by(requester_id=current_user.id)
            .order_by(desc(Order.created_at))
            .limit(10)
            .all()
        )
        activity = []
        for o in recent_orders:
            item_count = len(o.items) if o.items else 0
            activity.append({
                'id': o.id,
                'type': 'order',
                'description': f"Order {o.order_number} — {item_count} item(s) · {o.status.capitalize()}",
                'status': o.status,
                'amount': o.total_amount,
                'created_at': o.created_at.isoformat()
            })
        return APIResponse.success(data=activity, message="Recent activity retrieved")
    except Exception as e:
        current_app.logger.error(f"Recent activity error: {str(e)}")
        return APIResponse.server_error(str(e))

@bp.route('/api/stock-alerts')
@login_required
def api_stock_alerts():
    """Get low-stock alerts only for products this user has previously ordered."""
    try:
        # Only surface alerts for products this org has ever ordered
        ordered_ids = db.session.query(OrderItem.product_id).join(Order).filter(
            Order.requester_id == current_user.id
        ).distinct().all()
        ordered_ids = [r[0] for r in ordered_ids]

        if not ordered_ids:
            return APIResponse.success(data=[], message="No stock alerts")

        products = Product.query.filter(Product.id.in_(ordered_ids)).all()
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
    """Get this user's orders with approval status tracking."""
    try:
        # Only show orders belonging to the current user
        all_orders = Order.query.filter_by(
            requester_id=current_user.id
        ).order_by(desc(Order.created_at)).all()

        approval_data = []
        for order in all_orders:
            sla_remaining = None
            if order.status == 'pending':
                time_remaining = (order.created_at + timedelta(hours=24)) - datetime.utcnow()
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

        if 'new_password' in data and data['new_password']:
            current_pw = data.get('current_password', '')
            if not current_user.check_password(current_pw):
                return APIResponse.error("Current password is incorrect", status_code=400)
            if len(data['new_password']) < 8:
                return APIResponse.error("Password must be at least 8 characters", status_code=400)
            current_user.set_password(data['new_password'])

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
    try:
        period = request.args.get('period', 'month')
        now = datetime.now()
        current_month = now.month
        current_year = now.year

        orders_query = Order.query.filter_by(
            requester_id=current_user.id,
            status='approved'
        )

        if period == 'month':
            orders_query = orders_query.filter(
                func.extract('month', Order.created_at) == current_month,
                func.extract('year', Order.created_at) == current_year
            )
            budget_cats = BudgetCategory.query.filter_by(
                month=current_month, year=current_year
            ).all()
        elif period == 'quarter':
            three_months_ago = now - timedelta(days=90)
            orders_query = orders_query.filter(Order.created_at >= three_months_ago)
            budget_cats = BudgetCategory.query.filter(
                BudgetCategory.year == current_year
            ).all()
        else:  # year
            orders_query = orders_query.filter(
                func.extract('year', Order.created_at) == current_year
            )
            budget_cats = BudgetCategory.query.filter_by(year=current_year).all()

        orders = orders_query.order_by(desc(Order.created_at)).all()
        total_spent = sum(o.total_amount or 0 for o in orders)

        # total_allocated: sum of BudgetCategory records, fall back to user's spend_limit
        total_allocated = sum(c.allocated for c in budget_cats) if budget_cats else float(current_user.spend_limit or 0)

        # Categories from BudgetCategory table
        categories = [c.to_dict() for c in budget_cats] if budget_cats else []

        # Top departments: group approved orders by requester department
        dept_totals = defaultdict(lambda: {'spent': 0.0, 'order_count': 0})
        for o in orders:
            dept = (o.requester.department if o.requester else None) or 'General'
            dept_totals[dept]['spent'] += o.total_amount or 0
            dept_totals[dept]['order_count'] += 1
        top_departments = sorted(
            [{'name': k, **v} for k, v in dept_totals.items()],
            key=lambda x: x['spent'],
            reverse=True
        )[:5]

        # Recent transactions from real approved orders
        recent_transactions = [
            {
                'order_number': o.order_number,
                'department': (o.requester.department if o.requester else None) or 'General',
                'amount': o.total_amount or 0,
                'date': o.created_at.isoformat(),
                'status': o.status
            }
            for o in orders[:10]
        ]

        return APIResponse.success(
            data={
                'total_allocated': total_allocated,
                'total_spent': total_spent,
                'total_remaining': total_allocated - total_spent,
                'percentage_used': (total_spent / total_allocated * 100) if total_allocated > 0 else 0,
                'categories': categories,
                'top_departments': top_departments,
                'recent_transactions': recent_transactions
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
    try:
        items = SyncQueue.query.order_by(desc(SyncQueue.created_at)).limit(50).all()
        return APIResponse.success(data=[i.to_dict() for i in items], message="Sync queue retrieved")
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
    try:
        page = int(request.args.get('page', 1))
        per_page = 25
        status_filter = request.args.get('status', '')

        query = ScanHistory.query.filter_by(user_id=current_user.id)
        if status_filter:
            query = query.filter_by(status=status_filter)

        total = query.count()
        scans = query.order_by(desc(ScanHistory.scan_time)).offset((page - 1) * per_page).limit(per_page).all()

        return APIResponse.success(
            data={
                'scans': [s.to_dict() for s in scans],
                'total_scans': total,
                'filtered_count': len(scans),
                'page': page,
                'per_page': per_page
            },
            message="Scan history retrieved"
        )
    except Exception as e:
        current_app.logger.error(f"Scan history error: {str(e)}")
        return APIResponse.server_error(str(e))

@bp.route('/api/shipments/<int:shipment_id>')
@login_required
def api_shipment_detail(shipment_id):
    try:
        shipment = Shipment.query.get_or_404(shipment_id)
        return APIResponse.success(data=shipment.to_dict(), message="Shipment retrieved")
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

# ============ MULTI-ITEM DISTRIBUTOR REQUEST ROUTES ============

def generate_request_number(prefix='REQ'):
    stamp = datetime.utcnow().strftime('%Y%m%d%H%M%S')
    today_prefix = f'{prefix}-{datetime.utcnow().strftime("%Y%m%d")}'
    sequence = DistributorRequest.query.filter(
        DistributorRequest.request_number.like(f'{today_prefix}%')
    ).count() + 1
    return f'{prefix}-{stamp}-{sequence:03d}'


def generate_hospital_request_number():
    stamp = datetime.utcnow().strftime('%Y%m%d%H%M%S')
    today_prefix = f'HRQ-{datetime.utcnow().strftime("%Y%m%d")}'
    sequence = HospitalRequest.query.filter(
        HospitalRequest.request_number.like(f'{today_prefix}%')
    ).count() + 1
    return f'HRQ-{stamp}-{sequence:03d}'


@bp.route('/distributor/requests')
@login_required
def distributor_requests_page():
    """Distributor view of their grouped multi-item requests to manufacturers."""
    if not is_distributor_account():
        flash('Distributor access required.', 'error')
        return redirect(url_for('main.dashboard'))

    today = date.today()
    default_start = today - timedelta(days=29)
    start_date = parse_report_date(request.args.get('start_date'), default_start)
    end_date = parse_report_date(request.args.get('end_date'), today)
    if start_date > end_date:
        start_date, end_date = end_date, start_date

    status_filter = (request.args.get('status') or 'all').strip().lower()

    query = DistributorRequest.query.filter_by(distributor_user_id=current_user.id)
    if status_filter != 'all':
        query = query.filter_by(status=status_filter)

    start_dt = datetime.combine(start_date, datetime.min.time())
    end_dt = datetime.combine(end_date + timedelta(days=1), datetime.min.time())
    query = query.filter(DistributorRequest.requested_at >= start_dt, DistributorRequest.requested_at < end_dt)

    requests_list = query.order_by(desc(DistributorRequest.requested_at)).all()

    summary = {
        'total_count': len(requests_list),
        'pending_count': sum(1 for r in requests_list if r.status in {'pending', 'approved', 'payment_validated'}),
        'completed_count': sum(1 for r in requests_list if r.status in {'supplied', 'completed'}),
        'total_amount': sum(r.total_amount or 0 for r in requests_list),
        'total_items': sum(r.item_count or 0 for r in requests_list),
    }

    return render_template(
        'distributor/requests.html',
        distributor_requests=requests_list,
        distributor_summary=summary,
        distributor_filters={
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat(),
            'status': status_filter,
        }
    )


@bp.route('/hospital/requests')
@login_required
def hospital_requests_page():
    """Hospital view of their requests to distributors."""
    today = date.today()
    default_start = today - timedelta(days=29)
    start_date = parse_report_date(request.args.get('start_date'), default_start)
    end_date = parse_report_date(request.args.get('end_date'), today)
    if start_date > end_date:
        start_date, end_date = end_date, start_date

    status_filter = (request.args.get('status') or 'all').strip().lower()

    query = HospitalRequest.query.filter_by(hospital_user_id=current_user.id)
    if status_filter != 'all':
        query = query.filter_by(status=status_filter)

    start_dt = datetime.combine(start_date, datetime.min.time())
    end_dt = datetime.combine(end_date + timedelta(days=1), datetime.min.time())
    query = query.filter(HospitalRequest.requested_at >= start_dt, HospitalRequest.requested_at < end_dt)

    requests_list = query.order_by(desc(HospitalRequest.requested_at)).all()

    summary = {
        'total_count': len(requests_list),
        'pending_count': sum(1 for r in requests_list if r.status in {'pending', 'approved'}),
        'completed_count': sum(1 for r in requests_list if r.status in {'supplied', 'completed'}),
        'total_amount': sum(r.total_amount or 0 for r in requests_list),
        'total_items': sum(r.item_count or 0 for r in requests_list),
    }

    return render_template(
        'distributor/hospital-requests.html',
        hospital_requests=requests_list,
        hospital_summary=summary,
        hospital_filters={
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat(),
            'status': status_filter,
        }
    )


@bp.route('/hospital/order')
@login_required
def hospital_order_page():
    """Hospital browse distributor catalog and submit multi-item requests."""
    distributors = User.query.filter_by(account_type='distributor').order_by(User.first_name).all()
    selected_distributor_id = request.args.get('distributor_id', type=int)
    return render_template(
        'distributor/hospital-order.html',
        distributors=distributors,
        selected_distributor_id=selected_distributor_id,
    )


@bp.route('/distributor/hospital-requests')
@login_required
def distributor_hospital_requests_page():
    """Distributor views all incoming hospital requests sent to them."""
    distributor = get_distributor_user_or_none()
    if not distributor:
        flash('Distributor access required.', 'error')
        return redirect(url_for('main.dashboard'))

    today = date.today()
    default_start = today - timedelta(days=29)
    start_date = parse_report_date(request.args.get('start_date'), default_start)
    end_date = parse_report_date(request.args.get('end_date'), today)
    if start_date > end_date:
        start_date, end_date = end_date, start_date

    status_filter = (request.args.get('status') or 'all').strip().lower()

    query = HospitalRequest.query.filter_by(distributor_user_id=distributor.id)
    if status_filter != 'all':
        query = query.filter_by(status=status_filter)

    start_dt = datetime.combine(start_date, datetime.min.time())
    end_dt = datetime.combine(end_date + timedelta(days=1), datetime.min.time())
    query = query.filter(HospitalRequest.requested_at >= start_dt, HospitalRequest.requested_at < end_dt)

    requests_list = query.order_by(desc(HospitalRequest.requested_at)).all()

    summary = {
        'total_count': len(requests_list),
        'pending_count': sum(1 for r in requests_list if r.status == 'pending'),
        'completed_count': sum(1 for r in requests_list if r.status in {'supplied', 'completed'}),
        'total_amount': sum(r.total_amount or 0 for r in requests_list),
        'total_items': sum(r.item_count or 0 for r in requests_list),
    }

    return render_template(
        'distributor/hospital-incoming.html',
        hospital_requests=requests_list,
        hospital_summary=summary,
        hospital_filters={
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat(),
            'status': status_filter,
        }
    )


# ---- API: Distributor Multi-Item Requests ----

@bp.route('/api/distributor/requests', methods=['GET', 'POST'])
@login_required
def api_distributor_requests():
    """List or create grouped multi-item distributor → manufacturer requests."""
    distributor = get_distributor_user_or_none()
    if not distributor:
        return APIResponse.forbidden('Distributor access required')

    if request.method == 'GET':
        status = (request.args.get('status') or 'all').strip().lower()
        query = DistributorRequest.query.filter_by(distributor_user_id=distributor.id)
        if status != 'all':
            query = query.filter_by(status=status)
        requests_list = query.order_by(desc(DistributorRequest.requested_at)).all()
        return APIResponse.success(
            data={
                'items': [r.to_dict() for r in requests_list],
                'summary': {
                    'count': len(requests_list),
                    'pending': sum(1 for r in requests_list if r.status in {'pending', 'payment_validated', 'approved'}),
                    'total_amount': sum(r.total_amount or 0 for r in requests_list),
                }
            },
            message='Distributor requests retrieved'
        )

    # POST – create a grouped request
    data = request.get_json() or {}
    items_payload = data.get('items') or []
    notes = (data.get('notes') or '').strip() or None

    if not items_payload:
        return APIResponse.validation_error({'items': 'At least one item is required'})

    # Validate all items first
    validated_items = []
    for entry in items_payload:
        try:
            product_id = int(entry.get('product_sku_id'))
            qty = int(entry.get('requested_quantity', 0))
        except (TypeError, ValueError):
            return APIResponse.validation_error({'items': 'Each item must have a valid product_sku_id and requested_quantity'})
        if qty <= 0:
            return APIResponse.validation_error({'items': f'Quantity must be > 0 for product {product_id}'})
        product = ProductSKU.query.filter_by(id=product_id, status='active').first()
        if not product:
            return APIResponse.not_found(f'Product {product_id}')
        validated_items.append({'product': product, 'qty': qty, 'notes': (entry.get('notes') or '').strip() or None})

    # All items must belong to the same manufacturer (enforced at request level)
    manufacturer_ids = {item['product'].manufacturer_id for item in validated_items}
    if len(manufacturer_ids) > 1:
        return APIResponse.validation_error({'items': 'All items in a single request must belong to the same manufacturer'})

    manufacturer_id = manufacturer_ids.pop()
    request_number = generate_request_number('REQ')

    dist_request = DistributorRequest(
        request_number=request_number,
        distributor_user_id=distributor.id,
        manufacturer_id=manufacturer_id,
        status='pending',
        payment_status='pending',
        notes=notes,
        total_amount=0,
        item_count=0,
    )
    db.session.add(dist_request)
    db.session.flush()

    total = 0
    for entry in validated_items:
        product = entry['product']
        qty = entry['qty']
        demand = DistributorDemand(
            demand_number=generate_demand_number(),
            request_id=dist_request.id,
            manufacturer_id=manufacturer_id,
            distributor_user_id=distributor.id,
            product_sku_id=product.id,
            requested_quantity=qty,
            unit_price=product.unit_price or 0,
            status='pending',
            payment_status='pending',
            notes=entry['notes'],
        )
        demand.recalculate_total()
        total += demand.total_amount or 0
        db.session.add(demand)

    dist_request.total_amount = total
    dist_request.item_count = len(validated_items)
    db.session.commit()

    return APIResponse.success(data=dist_request.to_dict(), message='Request submitted successfully', status_code=201)


@bp.route('/api/distributor/requests/<int:request_id>', methods=['GET'])
@login_required
def api_distributor_request_detail(request_id):
    """Get full detail of a distributor request including all demand items."""
    distributor = get_distributor_user_or_none()
    manufacturer = get_current_manufacturer_profile()

    dist_request = DistributorRequest.query.get(request_id)
    if not dist_request:
        return APIResponse.not_found('Request')

    # Allow access to the owning distributor OR the manufacturer it was sent to
    if distributor and dist_request.distributor_user_id != distributor.id:
        return APIResponse.forbidden('Access denied')
    if manufacturer and dist_request.manufacturer_id != manufacturer.id:
        return APIResponse.forbidden('Access denied')
    if not distributor and not manufacturer:
        return APIResponse.forbidden('Access denied')

    return APIResponse.success(data=dist_request.to_dict(), message='Request detail retrieved')


@bp.route('/api/distributor/requests/<int:request_id>/validate-payment', methods=['POST'])
@login_required
def api_distributor_request_validate_payment(request_id):
    """Distributor validates payment for an entire grouped request."""
    distributor = get_distributor_user_or_none()
    if not distributor:
        return APIResponse.forbidden('Distributor access required')

    dist_request = DistributorRequest.query.filter_by(id=request_id, distributor_user_id=distributor.id).first()
    if not dist_request:
        return APIResponse.not_found('Request')

    if dist_request.status not in {'pending', 'approved'}:
        return APIResponse.validation_error({'status': 'Payment can only be validated for pending or approved requests'})

    now = datetime.utcnow()
    dist_request.payment_status = 'validated'
    dist_request.status = 'payment_validated'
    dist_request.payment_validated_at = now

    for demand in dist_request.demands.all():
        if demand.status in {'pending', 'approved'}:
            demand.payment_status = 'validated'
            demand.status = 'payment_validated'
            demand.payment_validated_at = now

    db.session.commit()
    return APIResponse.success(data=dist_request.to_dict(), message='Payment validated for all items')


# ---- API: Manufacturer viewing grouped requests ----

@bp.route('/api/manufacturer/distributor-requests', methods=['GET'])
@login_required
def api_manufacturer_distributor_requests():
    """Manufacturer views all incoming grouped distributor requests."""
    manufacturer = get_current_manufacturer_profile()
    if not manufacturer:
        return APIResponse.forbidden('Manufacturer access required')

    status = (request.args.get('status') or 'all').strip().lower()
    query = DistributorRequest.query.filter_by(manufacturer_id=manufacturer.id)
    if status != 'all':
        query = query.filter_by(status=status)

    requests_list = query.order_by(desc(DistributorRequest.requested_at)).all()
    return APIResponse.success(
        data={
            'items': [r.to_dict() for r in requests_list],
            'summary': {
                'count': len(requests_list),
                'pending': sum(1 for r in requests_list if r.status in {'pending', 'payment_validated', 'approved'}),
                'total_amount': sum(r.total_amount or 0 for r in requests_list),
            }
        },
        message='Manufacturer distributor requests retrieved'
    )


# ---- API: Hospital Requests (hospital → distributor) ----

@bp.route('/api/hospital/distributors', methods=['GET'])
@login_required
def api_hospital_distributors():
    """List distributors who have inventory available for hospital ordering."""
    distributors = User.query.filter_by(account_type='distributor').order_by(User.first_name).all()
    data = []
    for dist in distributors:
        inv_count = DistributorInventory.query.filter_by(distributor_user_id=dist.id).count()
        if inv_count > 0:
            data.append({
                'id': dist.id,
                'name': f"{dist.first_name} {dist.last_name}",
                'email': dist.email,
                'inventory_count': inv_count,
            })
    return APIResponse.success(data=data, message='Distributors retrieved')


@bp.route('/api/hospital/distributors/<int:distributor_id>/catalog', methods=['GET'])
@login_required
def api_hospital_distributor_catalog(distributor_id):
    """Get products available from a specific distributor's inventory."""
    dist = User.query.filter_by(id=distributor_id, account_type='distributor').first()
    if not dist:
        return APIResponse.not_found('Distributor')

    items = DistributorInventory.query.filter_by(distributor_user_id=distributor_id).all()
    data = []
    for item in items:
        if (item.quantity or 0) <= 0:
            continue
        product = item.product_sku
        manufacturer = item.manufacturer
        pricing = DistributorSellingPrice.query.filter_by(
            distributor_user_id=distributor_id,
            manufacturer_id=item.manufacturer_id,
            product_sku_id=item.product_sku_id,
        ).first()
        selling_price = pricing.selling_price if pricing else (product.unit_price if product else 0) or 0
        data.append({
            'inventory_id': item.id,
            'product_sku_id': item.product_sku_id,
            'manufacturer_id': item.manufacturer_id,
            'product_name': product.name if product else 'Unknown',
            'sku': product.sku if product else 'N/A',
            'category': product.category if product else None,
            'description': product.description if product else None,
            'manufacturer_name': manufacturer.legal_entity_name if manufacturer else None,
            'available_quantity': item.quantity,
            'unit_price': selling_price,
        })
    return APIResponse.success(data=data, message='Distributor catalog retrieved')


@bp.route('/api/hospital/requests', methods=['GET', 'POST'])
@login_required
def api_hospital_requests():
    """List or create hospital purchase requests to distributors."""
    if request.method == 'GET':
        status = (request.args.get('status') or 'all').strip().lower()
        query = HospitalRequest.query.filter_by(hospital_user_id=current_user.id)
        if status != 'all':
            query = query.filter_by(status=status)
        requests_list = query.order_by(desc(HospitalRequest.requested_at)).all()
        return APIResponse.success(
            data={
                'items': [r.to_dict() for r in requests_list],
                'summary': {
                    'count': len(requests_list),
                    'pending': sum(1 for r in requests_list if r.status in {'pending', 'approved'}),
                    'total_amount': sum(r.total_amount or 0 for r in requests_list),
                }
            },
            message='Hospital requests retrieved'
        )

    # POST – create a new hospital request
    data = request.get_json() or {}
    distributor_id = data.get('distributor_id')
    items_payload = data.get('items') or []
    notes = (data.get('notes') or '').strip() or None

    if not distributor_id:
        return APIResponse.validation_error({'distributor_id': 'Distributor is required'})
    if not items_payload:
        return APIResponse.validation_error({'items': 'At least one item is required'})

    dist = User.query.filter_by(id=distributor_id, account_type='distributor').first()
    if not dist:
        return APIResponse.not_found('Distributor')

    validated_items = []
    for entry in items_payload:
        try:
            product_sku_id = int(entry.get('product_sku_id'))
            qty = int(entry.get('requested_quantity', 0))
        except (TypeError, ValueError):
            return APIResponse.validation_error({'items': 'Each item must have valid product_sku_id and requested_quantity'})
        if qty <= 0:
            return APIResponse.validation_error({'items': 'Quantity must be greater than zero'})

        inv = DistributorInventory.query.filter_by(
            distributor_user_id=distributor_id,
            product_sku_id=product_sku_id,
        ).first()
        if not inv or (inv.quantity or 0) < qty:
            available = inv.quantity if inv else 0
            product = ProductSKU.query.get(product_sku_id)
            name = product.name if product else f'product {product_sku_id}'
            return APIResponse.validation_error({'items': f'Only {available} units available for {name}'})

        pricing = DistributorSellingPrice.query.filter_by(
            distributor_user_id=distributor_id,
            manufacturer_id=inv.manufacturer_id,
            product_sku_id=product_sku_id,
        ).first()
        unit_price = pricing.selling_price if pricing else (inv.product_sku.unit_price if inv.product_sku else 0) or 0

        validated_items.append({
            'inventory': inv,
            'product_sku_id': product_sku_id,
            'manufacturer_id': inv.manufacturer_id,
            'qty': qty,
            'unit_price': unit_price,
            'notes': (entry.get('notes') or '').strip() or None,
        })

    request_number = generate_hospital_request_number()
    hosp_request = HospitalRequest(
        request_number=request_number,
        hospital_user_id=current_user.id,
        distributor_user_id=distributor_id,
        status='pending',
        notes=notes,
        total_amount=0,
        item_count=0,
    )
    db.session.add(hosp_request)
    db.session.flush()

    total = 0
    for entry in validated_items:
        subtotal = entry['unit_price'] * entry['qty']
        item = HospitalRequestItem(
            request_id=hosp_request.id,
            distributor_user_id=distributor_id,
            manufacturer_id=entry['manufacturer_id'],
            product_sku_id=entry['product_sku_id'],
            requested_quantity=entry['qty'],
            unit_price=entry['unit_price'],
            subtotal=subtotal,
            status='pending',
            notes=entry['notes'],
        )
        total += subtotal
        db.session.add(item)

    hosp_request.total_amount = total
    hosp_request.item_count = len(validated_items)
    db.session.commit()

    return APIResponse.success(data=hosp_request.to_dict(), message='Request submitted successfully', status_code=201)


@bp.route('/api/hospital/requests/<int:request_id>', methods=['GET'])
@login_required
def api_hospital_request_detail(request_id):
    """Get full detail of a hospital request."""
    hosp_request = HospitalRequest.query.get(request_id)
    if not hosp_request:
        return APIResponse.not_found('Request')

    # Allow access to the submitting hospital user OR the receiving distributor
    if current_user.id not in {hosp_request.hospital_user_id, hosp_request.distributor_user_id}:
        return APIResponse.forbidden('Access denied')

    return APIResponse.success(data=hosp_request.to_dict(), message='Request detail retrieved')


# ---- Distributor: receiving hospital requests ----

@bp.route('/api/distributor/hospital-requests', methods=['GET'])
@login_required
def api_distributor_hospital_requests():
    """Distributor views hospital requests sent to them."""
    distributor = get_distributor_user_or_none()
    if not distributor:
        return APIResponse.forbidden('Distributor access required')

    status = (request.args.get('status') or 'all').strip().lower()
    query = HospitalRequest.query.filter_by(distributor_user_id=distributor.id)
    if status != 'all':
        query = query.filter_by(status=status)

    requests_list = query.order_by(desc(HospitalRequest.requested_at)).all()
    return APIResponse.success(
        data={
            'items': [r.to_dict() for r in requests_list],
            'summary': {
                'count': len(requests_list),
                'pending': sum(1 for r in requests_list if r.status in {'pending', 'approved'}),
                'total_amount': sum(r.total_amount or 0 for r in requests_list),
            }
        },
        message='Hospital requests retrieved'
    )


@bp.route('/api/distributor/hospital-requests/<int:request_id>/approve', methods=['POST'])
@login_required
def api_distributor_approve_hospital_request(request_id):
    """Distributor approves a hospital request."""
    distributor = get_distributor_user_or_none()
    if not distributor:
        return APIResponse.forbidden('Distributor access required')

    hosp_request = HospitalRequest.query.filter_by(id=request_id, distributor_user_id=distributor.id).first()
    if not hosp_request:
        return APIResponse.not_found('Request')

    if hosp_request.status != 'pending':
        return APIResponse.validation_error({'status': 'Only pending requests can be approved'})

    hosp_request.status = 'approved'
    hosp_request.approved_at = datetime.utcnow()
    for item in hosp_request.items:
        item.status = 'approved'
        item.approved_quantity = item.requested_quantity
        item.recalculate_subtotal()
    db.session.commit()

    return APIResponse.success(data=hosp_request.to_dict(), message='Request approved')


@bp.route('/api/distributor/hospital-requests/<int:request_id>/reject', methods=['POST'])
@login_required
def api_distributor_reject_hospital_request(request_id):
    """Distributor rejects a hospital request."""
    distributor = get_distributor_user_or_none()
    if not distributor:
        return APIResponse.forbidden('Distributor access required')

    hosp_request = HospitalRequest.query.filter_by(id=request_id, distributor_user_id=distributor.id).first()
    if not hosp_request:
        return APIResponse.not_found('Request')

    data = request.get_json() or {}
    hosp_request.status = 'rejected'
    for item in hosp_request.items:
        item.status = 'rejected'
        item.notes = (data.get('reason') or '').strip() or item.notes
    db.session.commit()

    return APIResponse.success(data=hosp_request.to_dict(), message='Request rejected')


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