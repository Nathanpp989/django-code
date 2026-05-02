"""
Structured logging and audit monitoring utilities.

Provides:
- Structured logging with request context
- Audit trail recording for sensitive operations
- Brute force attack detection
- User activity tracking
"""

import logging
import uuid
import hashlib
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
from collections import defaultdict

from asgiref.sync import sync_to_async
from django.contrib.auth.models import User
from django.core.cache import cache
from django.utils import timezone

# Import models
from django_llm.models import AuditLog, UserActivity


class StructuredLogger:
    """Structured logging with request context and user info."""

    def __init__(self, name: str):
        self.logger = logging.getLogger(name)
        self.request_context = {}

    def set_request_context(self, request_id: str, user: Optional[User] = None,
                           ip_address: Optional[str] = None):
        """Set context for current request."""
        self.request_context = {
            'request_id': request_id,
            'user_id': user.id if user else None,
            'username': user.username if user else 'anonymous',
            'ip_address': ip_address,
        }

    def _add_context(self, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Add request context to log record."""
        context = self.request_context.copy()
        if extra:
            context.update(extra)
        return context

    def debug(self, msg: str, extra: Optional[Dict[str, Any]] = None):
        """Log debug message with context."""
        self.logger.debug(msg, extra={'context': self._add_context(extra)})

    def info(self, msg: str, extra: Optional[Dict[str, Any]] = None):
        """Log info message with context."""
        self.logger.info(msg, extra={'context': self._add_context(extra)})

    def warning(self, msg: str, extra: Optional[Dict[str, Any]] = None):
        """Log warning message with context."""
        self.logger.warning(msg, extra={'context': self._add_context(extra)})

    def error(self, msg: str, extra: Optional[Dict[str, Any]] = None, exc_info: bool = False):
        """Log error message with context."""
        self.logger.error(msg, extra={'context': self._add_context(extra)}, exc_info=exc_info)

    def critical(self, msg: str, extra: Optional[Dict[str, Any]] = None):
        """Log critical message with context."""
        self.logger.critical(msg, extra={'context': self._add_context(extra)})


# Global logger instance
def get_structured_logger(name: str) -> StructuredLogger:
    """Get a structured logger instance."""
    return StructuredLogger(name)


# ============================================================================
# Brute Force Attack Detection
# ============================================================================

class BruteForceDetector:
    """Detect and track brute force auth attacks."""

    # Configuration
    MAX_ATTEMPTS = 5
    LOCKOUT_DURATION = 900  # 15 minutes in seconds
    ATTEMPT_WINDOW = 300    # 5 minutes in seconds

    @staticmethod
    def _get_cache_key(identifier: str, attempt_type: str = "login") -> str:
        """Generate cache key for tracking attempts."""
        return f"brute_force:{attempt_type}:{identifier}"

    @staticmethod
    async def record_failed_attempt(identifier: str, attempt_type: str = "auth") -> Dict[str, Any]:
        """Record a failed auth attempt and check if user should be locked out."""
        cache_key = BruteForceDetector._get_cache_key(identifier, attempt_type)
        
        # Get current attempt count
        attempt_data = cache.get(cache_key, {"attempts": 0, "locked_until": None})
        
        # Check if currently locked out
        if attempt_data.get("locked_until"):
            locked_until = attempt_data["locked_until"]
            if datetime.fromisoformat(locked_until) > datetime.now():
                return {
                    "locked": True,
                    "locked_until": locked_until,
                    "attempts": attempt_data["attempts"]
                }

        # Increment attempts
        attempt_data["attempts"] += 1
        
        # Check if should be locked out
        if attempt_data["attempts"] >= BruteForceDetector.MAX_ATTEMPTS:
            locked_until_dt = datetime.now() + timedelta(seconds=BruteForceDetector.LOCKOUT_DURATION)
            attempt_data["locked_until"] = locked_until_dt.isoformat()
            timeout = max(
                BruteForceDetector.ATTEMPT_WINDOW,
                int((locked_until_dt - datetime.now()).total_seconds()) + 1,
            )
        else:
            timeout = BruteForceDetector.ATTEMPT_WINDOW
        
        # Update cache
        cache.set(cache_key, attempt_data, timeout)
        
        return {
            "locked": attempt_data["attempts"] >= BruteForceDetector.MAX_ATTEMPTS,
            "locked_until": attempt_data.get("locked_until"),
            "attempts": attempt_data["attempts"]
        }

    @staticmethod
    async def record_success(identifier: str, attempt_type: str = "auth"):
        """Clear failed attempts on successful auth."""
        cache_key = BruteForceDetector._get_cache_key(identifier, attempt_type)
        cache.delete(cache_key)

    @staticmethod
    async def is_locked_out(identifier: str, attempt_type: str = "auth") -> bool:
        """Check if identifier is currently locked out."""
        cache_key = BruteForceDetector._get_cache_key(identifier, attempt_type)
        attempt_data = cache.get(cache_key, {})
        
        if not attempt_data.get("locked_until"):
            return False
        
        locked_until = datetime.fromisoformat(attempt_data["locked_until"])
        return locked_until > datetime.now()


# ============================================================================
# Audit Logging
# ============================================================================

@sync_to_async
def log_audit_trail(user: Optional[User], action: str, resource_type: str,
                   resource_id: Optional[int] = None, changes: Optional[Dict] = None,
                   ip_address: Optional[str] = None, user_agent: Optional[str] = None,
                   status: str = "success"):
    """Log an action to the audit trail."""
    try:
        AuditLog.objects.create(
            user=user,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            changes=changes,
            ip_address=ip_address,
            user_agent=user_agent,
            status=status,
        )
    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.error(f"Failed to log audit trail: {e}", exc_info=True)


@sync_to_async
def log_user_activity(user: User, activity_type: str, metadata: Optional[Dict] = None):
    """Log user activity for analytics."""
    try:
        UserActivity.objects.create(
            user=user,
            activity_type=activity_type,
            metadata=metadata or {},
        )
    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.error(f"Failed to log user activity: {e}", exc_info=True)


# ============================================================================
# Utility Functions
# ============================================================================

def generate_request_id() -> str:
    """Generate a unique request ID."""
    return str(uuid.uuid4())


def get_client_ip(request) -> str:
    """Extract client IP from request, accounting for proxies."""
    x_forwarded_for = request.headers.get('x-forwarded-for')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    
    x_real_ip = request.headers.get('x-real-ip')
    if x_real_ip:
        return x_real_ip.strip()
    
    return request.client[0] if request.client else "unknown"


def get_user_agent(request) -> str:
    """Extract user agent from request."""
    return request.headers.get('user-agent', 'unknown')


def get_password_hash(password: str, salt: Optional[str] = None) -> str:
    """Hash a password for logging purposes (not authentication)."""
    if not salt:
        salt = hashlib.sha256(password.encode()).hexdigest()[:8]
    
    hashed = hashlib.sha256(f"{password}{salt}".encode()).hexdigest()
    return f"sha256:{salt}:{hashed[:8]}..."


# ============================================================================
# Performance Monitoring
# ============================================================================

class RequestTimer:
    """Track request processing time."""
    
    def __init__(self, request_id: str, endpoint: str):
        self.request_id = request_id
        self.endpoint = endpoint
        self.start_time = datetime.now()

    def elapsed_ms(self) -> float:
        """Get elapsed time in milliseconds."""
        return (datetime.now() - self.start_time).total_seconds() * 1000

    def log(self, logger: StructuredLogger):
        """Log the request duration."""
        elapsed = self.elapsed_ms()
        status = "slow" if elapsed > 1000 else "normal"
        logger.info(
            f"Request completed: {self.endpoint}",
            extra={
                "elapsed_ms": elapsed,
                "status": status,
                "request_id": self.request_id,
            }
        )
