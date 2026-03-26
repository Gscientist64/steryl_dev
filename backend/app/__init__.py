# STERYL_UP/app/__init__.py
from flask import Flask, request
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_bcrypt import Bcrypt
from flask_cors import CORS
import os
from datetime import timedelta

# Initialize extensions
db = SQLAlchemy()
login_manager = LoginManager()
bcrypt = Bcrypt()

def create_app():
    """Application factory function"""
    app = Flask(__name__)
    
    # Configuration
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') or 'your-secret-key-change-this-in-production'
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL') or 'sqlite:///steryl.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    # Security configurations
    app.config['SESSION_COOKIE_SECURE'] = os.environ.get('SESSION_COOKIE_SECURE', 'False').lower() == 'true'
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)
    
    # Session security
    app.config['REMEMBER_COOKIE_SECURE'] = os.environ.get('REMEMBER_COOKIE_SECURE', 'False').lower() == 'true'
    app.config['REMEMBER_COOKIE_HTTPONLY'] = True
    app.config['REMEMBER_COOKIE_SAMESITE'] = 'Lax'
    
    # CSRF Protection (if using Flask-WTF)
    app.config['WTF_CSRF_ENABLED'] = True
    app.config['WTF_CSRF_SECRET_KEY'] = os.environ.get('CSRF_SECRET_KEY') or 'csrf-secret-key-change-this'
    
    # Logging configuration
    app.config['LOG_LEVEL'] = os.environ.get('LOG_LEVEL', 'INFO')
    app.config['LOG_TO_CONSOLE'] = app.debug or os.environ.get('LOG_TO_CONSOLE', 'False').lower() == 'true'
    app.config['LOG_REQUESTS'] = True
    app.config['LOG_RESPONSES'] = True
    
    # Email for error alerts (optional)
    if not app.debug:
        app.config['MAIL_SERVER'] = os.environ.get('MAIL_SERVER')
        app.config['MAIL_PORT'] = int(os.environ.get('MAIL_PORT', 25)) if os.environ.get('MAIL_PORT') else 25
        app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME')
        app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD')
        app.config['MAIL_DEFAULT_SENDER'] = os.environ.get('MAIL_DEFAULT_SENDER')
        app.config['MAIL_ADMINS'] = os.environ.get('MAIL_ADMINS', '').split(',') if os.environ.get('MAIL_ADMINS') else []
    else:
        # In development, disable email logging
        app.config['MAIL_SERVER'] = None
        app.config['MAIL_ADMINS'] = []
    
    # Rate limiting
    app.config['ENABLE_RATE_LIMITING'] = os.environ.get('ENABLE_RATE_LIMITING', 'True').lower() == 'true'
    
    # Enable CORS with more restrictive settings
    cors_origins = os.environ.get('CORS_ORIGINS', '*')
    if cors_origins != '*':
        cors_origins = cors_origins.split(',')
    
    CORS(app, resources={
        r"/api/*": {
            "origins": cors_origins,
            "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            "allow_headers": ["Content-Type", "Authorization"],
            "supports_credentials": True
        }
    })
    
    # Initialize extensions with app
    db.init_app(app)
    login_manager.init_app(app)
    bcrypt.init_app(app)
    
    # Configure login manager
    login_manager.login_view = 'main.login'
    login_manager.login_message = 'Please log in to access this page.'
    login_manager.login_message_category = 'info'
    login_manager.session_protection = 'strong'  # Additional security
    
    # Initialize logging (with error handling)
    try:
        from app.utils.logger import setup_logging, AuditLogger
        setup_logging(app)
        
        # Initialize audit logger
        audit_logger = AuditLogger()
        audit_logger.init_app(app)
        app.audit_logger = audit_logger
    except ImportError as e:
        print(f"Warning: Logging module not fully configured: {e}")
        app.audit_logger = None
    
    # Initialize error handler middleware
    try:
        from app.middleware.error_handler import ErrorHandler, SecurityMiddleware
        ErrorHandler(app)
        SecurityMiddleware(app)
    except ImportError as e:
        print(f"Warning: Error handling middleware not fully configured: {e}")
    
    # Add request start time for duration calculation
    @app.before_request
    def before_request():
        import time
        request.start_time = time.time()
    
    # User loader callback
    @login_manager.user_loader
    def load_user(user_id):
        from .models import User
        return User.query.get(int(user_id))
    
    # Import and register blueprints
    from . import routes
    app.register_blueprint(routes.bp)
    
    # Register error handlers
    @app.errorhandler(404)
    def not_found_error(error):
        return render_template('404.html'), 404
    
    @app.errorhandler(500)
    def internal_error(error):
        db.session.rollback()
        return render_template('500.html'), 500
    
    # Create tables
    with app.app_context():
        db.create_all()
        if hasattr(app, 'logger'):
            app.logger.info("Database tables created successfully")
    
    return app

# Create app instance
app = create_app()

# Add this for the render_template function
from flask import render_template