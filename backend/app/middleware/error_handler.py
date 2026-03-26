# STERYL_UP/app/middleware/error_handler.py
"""
Error Handling Middleware
"""
from flask import jsonify, request, current_app
from werkzeug.exceptions import HTTPException
from marshmallow import ValidationError
import traceback
import sys
from app.utils.response import APIResponse

class ErrorHandler:
    """Centralized error handling middleware"""
    
    def __init__(self, app=None):
        self.app = app
        if app:
            self.init_app(app)
    
    def init_app(self, app):
        """Initialize error handlers"""
        app.register_error_handler(Exception, self.handle_general_exception)
        app.register_error_handler(HTTPException, self.handle_http_exception)
        app.register_error_handler(ValidationError, self.handle_validation_error)
        
        # Register before request handler for request logging
        app.before_request(self.before_request)
        app.after_request(self.after_request)
    
    def before_request(self):
        """Log incoming requests"""
        if current_app.config.get('LOG_REQUESTS', True):
            current_app.logger.info(
                f"Request: {request.method} {request.path} - "
                f"IP: {request.remote_addr} - "
                f"User-Agent: {request.user_agent.string if request.user_agent else 'Unknown'}"
            )
    
    def after_request(self, response):
        """Log outgoing responses"""
        if current_app.config.get('LOG_RESPONSES', True):
            current_app.logger.info(
                f"Response: {request.method} {request.path} - "
                f"Status: {response.status_code} - "
                f"Duration: {self.get_request_duration()}ms"
            )
        return response
    
    def get_request_duration(self):
        """Calculate request duration if we have start time"""
        if hasattr(request, 'start_time'):
            import time
            return int((time.time() - request.start_time) * 1000)
        return 0
    
    def handle_general_exception(self, e):
        """Handle uncaught exceptions"""
        current_app.logger.error(
            f"Unhandled exception: {str(e)}\n{traceback.format_exc()}"
        )
        
        # In production, don't expose traceback
        if current_app.debug:
            error_details = {
                'type': type(e).__name__,
                'message': str(e),
                'traceback': traceback.format_exc().split('\n')
            }
            return APIResponse.server_error(
                message="An unexpected error occurred",
                errors=error_details
            )
        else:
            # Log the error but return generic message
            return APIResponse.server_error(
                message="An unexpected error occurred. Our team has been notified."
            )
    
    def handle_http_exception(self, e):
        """Handle HTTP exceptions"""
        current_app.logger.warning(
            f"HTTP Exception: {e.code} - {e.name} - {request.path} - "
            f"IP: {request.remote_addr}"
        )
        
        # Format the response based on status code
        if e.code == 404:
            return APIResponse.not_found(e.name)
        elif e.code == 401:
            return APIResponse.unauthorized(str(e.description) if e.description else e.name)
        elif e.code == 403:
            return APIResponse.forbidden(str(e.description) if e.description else e.name)
        elif e.code == 400:
            return APIResponse.error(
                message=str(e.description) if e.description else e.name,
                status_code=400
            )
        else:
            return APIResponse.error(
                message=e.description or e.name,
                status_code=e.code
            )
    
    def handle_validation_error(self, e):
        """Handle Marshmallow validation errors"""
        current_app.logger.warning(f"Validation error: {e.messages} - {request.path}")
        return APIResponse.validation_error(e.messages)

class SecurityMiddleware:
    """Security enhancements middleware"""
    
    def __init__(self, app=None):
        self.app = app
        if app:
            self.init_app(app)
    
    def init_app(self, app):
        """Initialize security headers"""
        app.after_request(self.add_security_headers)
        
        # Rate limiting (if using Flask-Limiter)
        if app.config.get('ENABLE_RATE_LIMITING', True):
            self.setup_rate_limiting(app)
    
    def add_security_headers(self, response):
        """Add security headers to all responses"""
        # HSTS (HTTP Strict Transport Security) - only in production
        if not current_app.debug:
            response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        
        # X-Content-Type-Options
        response.headers['X-Content-Type-Options'] = 'nosniff'
        
        # X-Frame-Options (prevent clickjacking)
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        
        # X-XSS-Protection
        response.headers['X-XSS-Protection'] = '1; mode=block'
        
        # Content Security Policy (UPDATED to allow required resources)
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.tailwindcss.com https://cdnjs.cloudflare.com https://fonts.googleapis.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdnjs.cloudflare.com https://cdn.tailwindcss.com; "
            "font-src 'self' https://fonts.gstatic.com https://cdnjs.cloudflare.com; "
            "img-src 'self' data: https://images.unsplash.com https:; "
            "connect-src 'self' http://localhost:5003; "
            "frame-src 'self'; "
            "object-src 'none'; "
            "base-uri 'self'; "
            "form-action 'self'"
        )
        
        # Referrer Policy
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        
        # Permissions Policy
        response.headers['Permissions-Policy'] = 'geolocation=(), microphone=(), camera=()'
        
        return response
    
    def setup_rate_limiting(self, app):
        """Setup rate limiting for sensitive endpoints"""
        # This is a placeholder. You'll need to install Flask-Limiter
        # and configure it properly
        try:
            from flask_limiter import Limiter
            from flask_limiter.util import get_remote_address
            
            limiter = Limiter(
                app=app,
                key_func=get_remote_address,
                default_limits=["200 per day", "50 per hour"],
                enabled=not app.debug  # Disable in debug mode
            )
            
            # Apply to specific endpoints (to be decorated in routes)
            app.config['RATELIMIT_ENABLED'] = True
            app.config['RATELIMIT_STORAGE_URL'] = 'memory://'
            
            app.logger.info("Rate limiting configured")
            
        except ImportError:
            app.logger.warning("Flask-Limiter not installed. Rate limiting disabled.")