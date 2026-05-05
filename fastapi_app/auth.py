"""
Authentication for FastAPI that shares Django sessions.

FastAPI reads the Django session cookie from the request,
looks up the session in Django's session store,
and returns the authenticated Django user.

This means any user logged into Django is automatically
authenticated in the FastAPI layer with no separate login needed.

Includes:
- Session validation
- Brute force attack detection
- Audit logging for auth events
"""

from asgiref.sync import sync_to_async
from fastapi import Request, HTTPException, status, Depends
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.auth.models import User
import logging

from fastapi_app.logging_utils import (
    BruteForceDetector, log_audit_trail, get_client_ip, get_user_agent
)

logger = logging.getLogger(__name__)


async def get_current_user(request: Request) -> User:
    """
    Dependency that extracts and validates the Django session.
    Use in any FastAPI endpoint that requires authentication:

        @router.get("/protected")
        async def protected(user: User = Depends(get_current_user)):
            return {"username": user.username}
    
    Includes brute force detection for invalid sessions.
    """
    session_key = request.cookies.get("sessionid")
    client_ip = get_client_ip(request)
    user_agent = get_user_agent(request)

    if await BruteForceDetector.is_locked_out(client_ip, "auth"):
        logger.warning(f"Auth blocked: too many failed attempts from {client_ip}")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed authentication attempts. Please try again later.",
            headers={"Retry-After": str(BruteForceDetector.LOCKOUT_DURATION)},
        )

    if not session_key:
        # Track failed auth attempts
        await BruteForceDetector.record_failed_attempt(client_ip, "auth")
        logger.warning(f"Auth failed: No session key from {client_ip}")
        
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated. Please log in via the Django interface.",
            headers={"WWW-Authenticate": "Session"},
        )

    try:
        session = SessionStore(session_key=session_key)
        session_data = await sync_to_async(session.load, thread_sensitive=True)()
        user_id = session_data.get("_auth_user_id")

        if not user_id:
            await BruteForceDetector.record_failed_attempt(client_ip, "auth")
            logger.warning(f"Auth failed: Invalid session from {client_ip}")
            
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Session expired or invalid. Please log in again.",
            )

        user = await sync_to_async(User.objects.select_related().get, thread_sensitive=True)(pk=user_id)

        if not user.is_active:
            await BruteForceDetector.record_failed_attempt(client_ip, "auth")
            logger.warning(f"Auth blocked: Inactive user {user.username} from {client_ip}")
            
            # Log audit trail for suspicious activity
            await log_audit_trail(
                user=user,
                action="LOGIN",
                resource_type="Session",
                ip_address=client_ip,
                user_agent=user_agent,
                status="failed",
            )
            
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is disabled.",
            )

        # Clear any failed attempts on successful auth
        await BruteForceDetector.record_success(client_ip, "auth")
        
        logger.info(f"Auth success: User {user.username} from {client_ip}")
        
        # Log successful session auth
        await log_audit_trail(
            user=user,
            action="LOGIN",
            resource_type="Session",
            ip_address=client_ip,
            user_agent=user_agent,
            status="success",
        )
        
        return user

    except User.DoesNotExist:
        await BruteForceDetector.record_failed_attempt(client_ip, "auth")
        logger.warning(f"Auth failed: User not found, session {session_key[:8]}... from {client_ip}")
        
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found. Please log in again.",
        )
    except HTTPException:
        raise
    except Exception as e:
        await BruteForceDetector.record_failed_attempt(client_ip, "auth")
        logger.error(f"Session auth error from {client_ip}: {e}", exc_info=True)
        
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed.",
        )


async def get_current_admin_user(user: User = Depends(get_current_user)) -> User:
    """
    Dependency that requires the user to be a Django staff member.
    Use for admin-only endpoints.
    """
    if not user.is_staff:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required.",
        )
    return user
