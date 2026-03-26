# STERYL_UP/app/utils/response.py
"""
API Response Formatter - Standardizes all API responses
"""
from flask import jsonify
from typing import Any, Dict, Optional, Union
from werkzeug.exceptions import HTTPException

class APIResponse:
    """Standard API response formatter"""
    
    @staticmethod
    def success(
        data: Any = None,
        message: str = "Success",
        status_code: int = 200,
        meta: Optional[Dict] = None
    ) -> tuple:
        """Format success response"""
        response = {
            "success": True,
            "message": message,
            "data": data,
            "status_code": status_code
        }
        
        if meta:
            response["meta"] = meta
            
        return jsonify(response), status_code
    
    @staticmethod
    def error(
        message: str = "An error occurred",
        status_code: int = 400,
        errors: Optional[Union[Dict, list]] = None,
        error_code: Optional[str] = None
    ) -> tuple:
        """Format error response"""
        response = {
            "success": False,
            "message": message,
            "status_code": status_code
        }
        
        if errors:
            response["errors"] = errors
        
        if error_code:
            response["error_code"] = error_code
            
        return jsonify(response), status_code
    
    @staticmethod
    def validation_error(errors: Dict) -> tuple:
        """Format validation error response"""
        return APIResponse.error(
            message="Validation failed",
            status_code=400,
            errors=errors,
            error_code="VALIDATION_ERROR"
        )
    
    @staticmethod
    def unauthorized(message: str = "Unauthorized access") -> tuple:
        """Format unauthorized response"""
        return APIResponse.error(
            message=message,
            status_code=401,
            error_code="UNAUTHORIZED"
        )
    
    @staticmethod
    def forbidden(message: str = "Access forbidden") -> tuple:
        """Format forbidden response"""
        return APIResponse.error(
            message=message,
            status_code=403,
            error_code="FORBIDDEN"
        )
    
    @staticmethod
    def not_found(resource: str = "Resource") -> tuple:
        """Format not found response"""
        return APIResponse.error(
            message=f"{resource} not found",
            status_code=404,
            error_code="NOT_FOUND"
        )
    
    @staticmethod
    def conflict(message: str = "Resource conflict") -> tuple:
        """Format conflict response"""
        return APIResponse.error(
            message=message,
            status_code=409,
            error_code="CONFLICT"
        )
    
    @staticmethod
    def server_error(message: str = "Internal server error") -> tuple:
        """Format server error response"""
        return APIResponse.error(
            message=message,
            status_code=500,
            error_code="SERVER_ERROR"
        )