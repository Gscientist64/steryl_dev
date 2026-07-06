import uuid
from datetime import datetime, timedelta

from app import create_app, db
from app.models import User, Manufacturer, ProductSKU, Batch


def set_if_column(instance, field_name, value):
    if hasattr(type(instance), field_name):
        setattr(instance, field_name, value)


def get_or_create_distributor() -> User:
    email = "distributor@steryl.local"
    user = User.query.filter_by(email=email).first() if hasattr(User, "email") else None

    if user:
        if user.account_type != "distributor":
            user.account_type = "distributor"
        if not user.is_active:
            user.is_active = True
        db.session.commit()
        return user

    user = User(
        first_name="Steryl",
        last_name="Distributor",
        email=email,
        password="Distributor@123",
        phone="+2348000000001",
        country="Nigeria",
        account_type="distributor",
    )
    db.session.add(user)
    db.session.commit()
    return user


def get_or_create_demo_manufacturer() -> Manufacturer:
    manufacturer_user = User.query.filter_by(email="manufacturer@steryl.local").first() if hasattr(User, "email") else None
    if not manufacturer_user:
        manufacturer_user = User(
            first_name="Steryl",
            last_name="Manufacturer",
            email="manufacturer@steryl.local",
            password="Manufacturer@123",
            phone="+2348000000002",
            country="Nigeria",
            account_type="manufacturer",
        )
        db.session.add(manufacturer_user)
        db.session.commit()

    manufacturer = Manufacturer.query.filter_by(user_id=manufacturer_user.id).first()
    if manufacturer:
        return manufacturer

    manufacturer = Manufacturer()
    set_if_column(manufacturer, "user_id", manufacturer_user.id)
    set_if_column(manufacturer, "legal_entity_name", "Steryl Manufacturing Ltd")
    set_if_column(manufacturer, "medical_license_number", f"REG-{uuid.uuid4().hex[:8].upper()}")
    set_if_column(manufacturer, "business_address", "Demo Industrial Layout")
    set_if_column(manufacturer, "verification_status", "verified")
    db.session.add(manufacturer)
    db.session.commit()
    return manufacturer


def ensure_demo_catalog(manufacturer: Manufacturer) -> None:
    skus = [
        {
            "sku": "STER-N95-001",
            "name": "Steryl N95 Mask",
            "description": "Respiratory protective mask",
            "unit_price": 2.75,
            "batch_prefix": "N95",
            "quantity": 1000,
        },
        {
            "sku": "STER-GLO-010",
            "name": "Steryl Surgical Gloves",
            "description": "Disposable latex-free gloves",
            "unit_price": 0.35,
            "batch_prefix": "GLO",
            "quantity": 5000,
        },
        {
            "sku": "STER-SYR-100",
            "name": "Steryl 10ml Syringe",
            "description": "Single use sterile syringe",
            "unit_price": 0.48,
            "batch_prefix": "SYR",
            "quantity": 3000,
        },
    ]

    for idx, payload in enumerate(skus, start=1):
        sku = ProductSKU.query.filter_by(
            manufacturer_id=manufacturer.id,
            sku=payload["sku"],
        ).first()

        if not sku:
            sku = ProductSKU(
                manufacturer_id=manufacturer.id,
                sku=payload["sku"],
                name=payload["name"],
                description=payload["description"],
                unit_price=payload["unit_price"],
                status="active",
            )
            db.session.add(sku)
            db.session.flush()

        active_batch = (
            Batch.query.filter_by(product_sku_id=sku.id, status="active")
            .order_by(Batch.expiry_date.asc())
            .first()
        )

        if not active_batch:
            mfg_date = datetime.utcnow().date() - timedelta(days=30)
            exp_date = datetime.utcnow().date() + timedelta(days=300 + idx * 15)
            batch = Batch(
                product_sku_id=sku.id,
                batch_number=f"{payload['batch_prefix']}-{datetime.utcnow().strftime('%y%m')}-{idx:02d}",
                manufacturing_date=mfg_date,
                expiry_date=exp_date,
                quantity=payload["quantity"],
                status="active",
                location="Demo warehouse",
                is_verified=True,
            )
            db.session.add(batch)

    db.session.commit()


def main() -> None:
    app = create_app()
    with app.app_context():
        distributor = get_or_create_distributor()
        manufacturer = get_or_create_demo_manufacturer()
        ensure_demo_catalog(manufacturer)

        print("Distributor account is ready")
        print("Email: distributor@steryl.local")
        print("Password: Distributor@123")
        print("Manufacturer account is ready")
        print("Email: manufacturer@steryl.local")
        print("Password: Manufacturer@123")
        print("Demo manufacturer catalog and active batches are available for demands.")


if __name__ == "__main__":
    main()