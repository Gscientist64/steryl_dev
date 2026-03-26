# STERYL_UP/app/utils/logger.py
"""
Logging Configuration for Steryl Application
"""
import logging
import os
from logging.handlers import RotatingFileHandler
from datetime import datetime
import json
from flask import request, has_request_context

class JSONFormatter(logging.Formatter):
    """Custom JSON formatter for structured logging"""
    
    def format(self, record):
        log_data = {
            'timestamp': datetime.utcnow().isoformat(),
            'level': record.levelname,
            'name': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno
        }
        
        # Add exception info if present
        if record.exc_info:
            log_data['exception'] = self.formatException(record.exc_info)
        
        # Add request context if available
        if has_request_context():
            log_data['request'] = {
                'method': request.method,
                'url': request.url,
                'ip': request.remote_addr,
                'user_agent': request.user_agent.string if request.user_agent else None
            }
            if hasattr(request, 'user') and request.user:
                log_data['request']['user_id'] = request.user.id if hasattr(request.user, 'id') else None
        
        return json.dumps(log_data)

def setup_logging(app):
    """Configure logging for the application"""
    
    # Create logs directory if it doesn't exist
    log_dir = 'logs'
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    
    # Set log level from config
    log_level = getattr(logging, app.config.get('LOG_LEVEL', 'INFO'))
    
    # Remove default handlers
    app.logger.handlers.clear()
    
    # File handler - Rotating file with JSON format
    file_handler = RotatingFileHandler(
        os.path.join(log_dir, 'steryl.log'),
        maxBytes=10485760,  # 10MB
        backupCount=10
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(JSONFormatter())
    app.logger.addHandler(file_handler)
    
    # Error file handler - Only for errors
    error_handler = RotatingFileHandler(
        os.path.join(log_dir, 'steryl_error.log'),
        maxBytes=10485760,
        backupCount=20
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(JSONFormatter())
    app.logger.addHandler(error_handler)
    
    # Console handler - For development
    if app.debug or app.config.get('LOG_TO_CONSOLE'):
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.DEBUG if app.debug else logging.INFO)
        console_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        console_handler.setFormatter(console_formatter)
        app.logger.addHandler(console_handler)
    
    # Email handler - DISABLED IN DEVELOPMENT
    if not app.debug:
        # Only configure email handler in production and if mail settings exist
        if app.config.get('MAIL_SERVER') and app.config.get('MAIL_ADMINS'):
            try:
                from logging.handlers import SMTPHandler
                mail_handler = SMTPHandler(
                    mailhost=(app.config['MAIL_SERVER'], app.config.get('MAIL_PORT', 25)),
                    fromaddr=app.config.get('MAIL_DEFAULT_SENDER', 'errors@steryl.com'),
                    toaddrs=app.config['MAIL_ADMINS'],
                    subject='Steryl Application Error',
                    credentials=(app.config.get('MAIL_USERNAME'), app.config.get('MAIL_PASSWORD')) if app.config.get('MAIL_USERNAME') else None,
                    secure=()
                )
                mail_handler.setLevel(logging.ERROR)
                mail_handler.setFormatter(logging.Formatter(
                    '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
                ))
                app.logger.addHandler(mail_handler)
                app.logger.info("Email error handler configured")
            except Exception as e:
                app.logger.warning(f"Could not configure email error handler: {e}")
        else:
            app.logger.info("Email error handler not configured (missing settings)")
    else:
        app.logger.info("Email error handler disabled in debug mode")
    
    # Set SQLAlchemy logging level
    logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)
    
    app.logger.info('Logging configured successfully')
    return app.logger

class AuditLogger:
    """Specialized logger for audit trails"""
    
    def __init__(self, app=None):
        self.app = app
        self.logger = None
    
    def init_app(self, app):
        self.app = app
        self.logger = logging.getLogger('audit')
        
        # Audit file handler
        audit_handler = RotatingFileHandler(
            'logs/audit.log',
            maxBytes=10485760,
            backupCount=30
        )
        audit_handler.setLevel(logging.INFO)
        audit_handler.setFormatter(JSONFormatter())
        self.logger.addHandler(audit_handler)
    
    def log_action(self, user_id, action, resource, resource_id=None, details=None, ip_address=None):
        """Log user actions for audit trail"""
        log_data = {
            'user_id': user_id,
            'action': action,
            'resource': resource,
            'resource_id': resource_id,
            'details': details,
            'ip_address': ip_address or (request.remote_addr if has_request_context() else None),
            'timestamp': datetime.utcnow().isoformat()
        }
        
        self.logger.info(json.dumps(log_data))