# STERYL_UP/app/routes.py
from flask import render_template, redirect, url_for, flash, request, jsonify, Blueprint, current_app, session
from flask_login import login_user, login_required, logout_user, current_user
from . import db, bcrypt
from .models import User
from app.utils.response import APIResponse
from app.utils.validators import UserLoginSchema, UserRegisterSchema, validate_with_schema
from werkzeug.security import check_password_hash
import re

bp = Blueprint('main', __name__)

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
            # Get JSON data
            data = request.get_json()
            if not data:
                return APIResponse.error("Invalid request format", 400)
            
            # Validate with Marshmallow
            is_valid, validated_data, errors = validate_with_schema(
                UserLoginSchema(), data
            )
            
            if not is_valid:
                current_app.logger.warning(f"Login validation failed for IP: {request.remote_addr}")
                return APIResponse.validation_error(errors)
            
            # Check if user exists
            user = User.query.filter_by(email=validated_data['email'].lower()).first()
            
            if user:
                # Try bcrypt first, fallback to werkzeug
                password_valid = False
                try:
                    # Try with bcrypt (for new users)
                    password_valid = bcrypt.check_password_hash(user.password, validated_data['password'])
                except Exception as e:
                    current_app.logger.warning(f"Bcrypt check failed, trying werkzeug: {e}")
                    try:
                        # Fallback to werkzeug (for old users)
                        password_valid = check_password_hash(user.password, validated_data['password'])
                    except Exception as e2:
                        current_app.logger.error(f"Both password checks failed: {e2}")
                        password_valid = False
                
                if password_valid:
                    # Log successful login
                    login_user(user, remember=validated_data['remember'])
                    current_app.logger.info(f"User {user.email} logged in successfully")
                    
                    # If using audit logger, uncomment:
                    # if hasattr(current_app, 'audit_logger') and current_app.audit_logger:
                    #     current_app.audit_logger.log_action(
                    #         user_id=user.id,
                    #         action='login',
                    #         resource='user',
                    #         resource_id=user.id,
                    #         ip_address=request.remote_addr
                    #     )
                    
                    return APIResponse.success(
                        data={'user': user.to_dict()},
                        message="Login successful",
                        meta={'redirect': url_for('main.index')}
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
            
            # Validate with Marshmallow
            is_valid, validated_data, errors = validate_with_schema(
                UserRegisterSchema(), data
            )
            
            if not is_valid:
                current_app.logger.warning(f"Registration validation failed: {errors}")
                return APIResponse.validation_error(errors)
            
            # Check if email already exists
            existing_user = User.query.filter_by(email=validated_data['email']).first()
            if existing_user:
                return APIResponse.conflict("Email already registered. Please login instead.")
            
            # Create new user - this will use bcrypt automatically
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
            
            # Log the registration
            current_app.logger.info(f"New user registered: {new_user.email}")
            
            # Log the user in automatically
            login_user(new_user)
            
            return APIResponse.success(
                data={'user': new_user.to_dict()},
                message="Account created successfully",
                status_code=201,
                meta={'redirect': url_for('main.index')}
            )
            
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Registration error: {str(e)}", exc_info=True)
            return APIResponse.server_error("An error occurred during registration")

@bp.route('/logout')
@login_required
def logout():
    """Handle user logout"""
    user_id = current_user.id
    user_email = current_user.email
    
    logout_user()
    
    current_app.logger.info(f"User {user_email} logged out")
    
    flash('You have been logged out successfully.', 'info')
    return redirect(url_for('main.login'))

@bp.route('/about')
def about():
    return render_template('about.html')

@bp.route('/solutions')
def solutions():
    return render_template('solutions.html')

@bp.route('/how-it-works')
def how_it_works():
    return render_template('how-it-works.html')

# Health check endpoint for monitoring
@bp.route('/health')
def health_check():
    """Health check endpoint for monitoring"""
    try:
        # Check database connection
        db.session.execute('SELECT 1')
        return APIResponse.success(
            data={'status': 'healthy', 'database': 'connected'},
            message="System is healthy"
        )
    except Exception as e:
        current_app.logger.error(f"Health check failed: {str(e)}")
        return APIResponse.server_error("Health check failed")