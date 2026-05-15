# STERYL_UP/app/__init__.py (top of the file)
import os
from dotenv import load_dotenv
from flask import Flask, request
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_bcrypt import Bcrypt
from flask_cors import CORS
from datetime import timedelta

# Load environment variables from .env file - MUST BE FIRST
load_dotenv()

# Print for debugging (remove in production)
print(f"Loading database from: {os.getenv('DATABASE_URL', 'Using default SQLite')}")

# Initialize extensions
db = SQLAlchemy()
login_manager = LoginManager()
bcrypt = Bcrypt()

def create_app():
    """Application factory function"""
    app = Flask(__name__)
    
    # Get database URL from environment
    database_url = os.environ.get('DATABASE_URL')
    
    # If no DATABASE_URL, use PostgreSQL with default values
    if not database_url:
        database_url = 'postgresql://postgres:lamis@localhost:5432/steryl_db'
        print(f"⚠️  No DATABASE_URL found, using default: {database_url}")
    else:
        print(f"✅ Using DATABASE_URL from environment: {database_url[:30]}...")  # Only show first 30 chars
    
    # Configuration
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') or 'your-secret-key-change-this-in-production'
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'pool_pre_ping': True,
        'pool_recycle': 3600,
    }
    
    # Security configurations
    app.config['SESSION_COOKIE_SECURE'] = os.environ.get('SESSION_COOKIE_SECURE', 'False').lower() == 'true'
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)
    
    # Rest of your configuration...
    
    # Enable CORS with more restrictive settings
    CORS(app, resources={
        r"/api/*": {
            "origins": os.environ.get('CORS_ORIGINS', '*').split(','),
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