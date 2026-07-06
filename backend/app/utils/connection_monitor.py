# STERYL_UP/app/utils/connection_monitor.py
"""
Monitor and log database connection usage
"""
from flask import current_app
from sqlalchemy import text
from app import db
from datetime import datetime

class ConnectionMonitor:
    """Monitors database connection usage"""
    
    @staticmethod
    def get_connection_stats():
        """Get current connection statistics"""
        try:
            with db.engine.connect() as conn:
                # Get total connections
                total = conn.execute(text("""
                    SELECT count(*) FROM pg_stat_activity 
                    WHERE datname = current_database()
                """)).scalar()
                
                # Get active connections
                active = conn.execute(text("""
                    SELECT count(*) FROM pg_stat_activity 
                    WHERE datname = current_database() 
                    AND state = 'active'
                """)).scalar()
                
                # Get idle connections
                idle = conn.execute(text("""
                    SELECT count(*) FROM pg_stat_activity 
                    WHERE datname = current_database() 
                    AND state = 'idle'
                """)).scalar()
                
                return {
                    'total': total,
                    'active': active,
                    'idle': idle,
                    'timestamp': datetime.now().isoformat()
                }
        except Exception as e:
            if current_app:
                current_app.logger.error(f"Failed to get connection stats: {str(e)}")
            return None
    
    @staticmethod
    def log_connection_stats():
        """Log connection statistics for monitoring"""
        stats = ConnectionMonitor.get_connection_stats()
        if stats and current_app:
            current_app.logger.info(
                f"DB Connections - Total: {stats['total']}, "
                f"Active: {stats['active']}, Idle: {stats['idle']}"
            )