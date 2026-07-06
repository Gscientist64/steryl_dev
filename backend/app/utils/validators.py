# STERYL_UP/app/utils/validators.py
"""
Marshmallow Schemas for Request Validation
"""
from marshmallow import Schema, fields, validate, ValidationError, validates_schema
from marshmallow import validates
import re
from datetime import datetime
import phonenumbers

class UserRegisterSchema(Schema):
    """Validation schema for unified organization registration"""
    first_name = fields.Str(
        required=True,
        validate=validate.Length(min=2, max=120),
        error_messages={"required": "First name is required"}
    )
    last_name = fields.Str(
        required=True,
        validate=validate.Length(min=2, max=120),
        error_messages={"required": "Last name is required"}
    )
    email = fields.Email(
        required=True,
        error_messages={"required": "Email is required", "invalid": "Invalid email format"}
    )
    password = fields.Str(
        required=True,
        validate=validate.Length(min=8),
        error_messages={"required": "Password is required"}
    )
    confirm_password = fields.Str(
        required=True,
        error_messages={"required": "Please confirm your password"}
    )
    phone = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(max=20)
    )
    country = fields.Str(
        required=True,
        validate=validate.Length(min=2),
        error_messages={"required": "Country is required"}
    )
    account_type = fields.Str(
        required=True,
        validate=validate.OneOf(
            ['hospital', 'laboratory', 'pharmacy', 'manufacturer'],
            error="Invalid account type. Must be one of: hospital, laboratory, pharmacy, manufacturer"
        ),
        error_messages={"required": "Account type is required"}
    )
    organization_name = fields.Str(
        required=True,
        validate=validate.Length(min=2, max=200),
        error_messages={"required": "Organization name is required"}
    )
    license_number = fields.Str(required=False, allow_none=True, load_default=None)
    business_address = fields.Str(required=False, allow_none=True, load_default=None)
    terms = fields.Bool(
        required=True,
        error_messages={"required": "You must agree to terms"}
    )

    @validates_schema
    def validate_passwords_match(self, data, **kwargs):
        if data.get('password') != data.get('confirm_password'):
            raise ValidationError("Passwords do not match", field_name="confirm_password")

    @validates('terms')
    def validate_terms(self, value, **kwargs):
        if not value:
            raise ValidationError("You must accept the terms and conditions")
        return value

    @validates('phone')
    def validate_phone(self, value, **kwargs):
        if value:
            try:
                phone_obj = phonenumbers.parse(value, None)
                if not phonenumbers.is_valid_number(phone_obj):
                    raise ValidationError("Invalid phone number format")
            except:
                phone_pattern = r'^[\d\s\-\+\(\)]{7,}$'
                if not re.match(phone_pattern, value):
                    raise ValidationError("Invalid phone number format")
        return value

class UserLoginSchema(Schema):
    """Validation schema for user login"""
    email = fields.Email(
        required=True,
        error_messages={"required": "Email is required", "invalid": "Invalid email format"}
    )
    password = fields.Str(
        required=True,
        validate=validate.Length(min=6),
        error_messages={"required": "Password is required"}
    )
    remember = fields.Bool(required=False, load_default=False)

class InventoryItemSchema(Schema):
    """Validation schema for inventory items"""
    name = fields.Str(
        required=True,
        validate=validate.Length(min=2, max=200),
        error_messages={"required": "Item name is required"}
    )
    description = fields.Str(required=False, allow_none=True)
    category = fields.Str(
        required=True,
        validate=validate.Length(min=2, max=100),
        error_messages={"required": "Category is required"}
    )
    sku = fields.Str(
        required=True,
        validate=validate.Length(min=2, max=50),
        error_messages={"required": "SKU is required"}
    )
    quantity = fields.Int(
        required=True,
        validate=validate.Range(min=0),
        error_messages={"required": "Quantity is required"}
    )
    unit_price = fields.Decimal(
        required=True,
        validate=validate.Range(min=0),
        error_messages={"required": "Unit price is required"}
    )
    reorder_level = fields.Int(
        required=False,
        validate=validate.Range(min=0),
        load_default=0
    )
    expiry_date = fields.Date(required=False, allow_none=True)
    supplier_id = fields.Int(required=False, allow_none=True)
    
    @validates('expiry_date')
    def validate_expiry_date(self, value, **kwargs):
        """Validate expiry date is in the future"""
        if value and value < datetime.now().date():
            raise ValidationError("Expiry date must be in the future")
        return value

class OrderCreateSchema(Schema):
    """Validation schema for creating orders"""
    order_type = fields.Str(
        required=True,
        validate=validate.OneOf(['purchase', 'request', 'transfer']),
        error_messages={"required": "Order type is required"}
    )
    items = fields.List(
        fields.Dict(),
        required=True,
        validate=validate.Length(min=1),
        error_messages={"required": "At least one item is required"}
    )
    notes = fields.Str(required=False, allow_none=True)
    priority = fields.Str(
        required=False,
        validate=validate.OneOf(['low', 'normal', 'high', 'urgent']),
        load_default='normal'
    )
    
    @validates_schema
    def validate_items(self, data, **kwargs):
        """Validate each item in the order"""
        items = data.get('items', [])
        for idx, item in enumerate(items):
            if 'item_id' not in item:
                raise ValidationError(f"Item {idx + 1}: item_id is required", field_name="items")
            if 'quantity' not in item:
                raise ValidationError(f"Item {idx + 1}: quantity is required", field_name="items")
            if not isinstance(item.get('quantity'), (int, float)) or item['quantity'] <= 0:
                raise ValidationError(f"Item {idx + 1}: quantity must be a positive number", field_name="items")

class PatientCreateSchema(Schema):
    """Validation schema for creating patients"""
    first_name = fields.Str(
        required=True,
        validate=validate.Length(min=2, max=120),
        error_messages={"required": "First name is required"}
    )
    last_name = fields.Str(
        required=True,
        validate=validate.Length(min=2, max=120),
        error_messages={"required": "Last name is required"}
    )
    date_of_birth = fields.Date(
        required=True,
        error_messages={"required": "Date of birth is required"}
    )
    gender = fields.Str(
        required=True,
        validate=validate.OneOf(['male', 'female', 'other']),
        error_messages={"required": "Gender is required"}
    )
    email = fields.Email(required=False, allow_none=True)
    phone = fields.Str(required=False, allow_none=True)
    address = fields.Str(required=False, allow_none=True)
    blood_type = fields.Str(
        required=False,
        validate=validate.OneOf(['A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-']),
        allow_none=True
    )
    allergies = fields.Str(required=False, allow_none=True)
    medical_history = fields.Str(required=False, allow_none=True)
    
    @validates('date_of_birth')
    def validate_age(self, value, **kwargs):
        """Validate patient is at least 0 years old and not in the future"""
        if value > datetime.now().date():
            raise ValidationError("Date of birth cannot be in the future")
        return value

def validate_with_schema(schema, data, partial=False):
    """
    Helper function to validate data with marshmallow schema
    Returns: (is_valid, validated_data, errors)
    """
    try:
        validated_data = schema.load(data, partial=partial)
        return True, validated_data, None
    except ValidationError as err:
        return False, None, err.messages