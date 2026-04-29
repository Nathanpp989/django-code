"""
Authentication for FastAPI that shares Django sessions.

FastAPI reads the Django session cookie from the request,
looks up the session in Django's session store,
and returns the authenticated Django user.

This means any user logged into Django is automatically
authenticated in the FastAPI layer with no separate login needed.
"""

from fastapi import Request, HTTPException, status, Depends
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.auth.models import User
import logging

logger = logging.getLogger(__name__)


async def get_current_user(request: Request) -> User:
    """
    Dependency that extracts and validates the Django session.
    Use in any FastAPI endpoint that requires authentication:

        @router.get("/protected")
        async def protected(user: User = Depends(get_current_user)):
            return {"username": user.username}
    """
    session_key = request.cookies.get("sessionid")

    if not session_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated. Please log in via the Django interface.",
            headers={"WWW-Authenticate": "Session"},
        )

    try:
        session = SessionStore(session_key=session_key)
        session_data = session.load()
        user_id = session_data.get("_auth_user_id")

        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Session expired or invalid. Please log in again.",
            )

        user = User.objects.select_related().get(pk=user_id)

        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is disabled.",
            )

        return user

    except User.DoesNotExist:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found. Please log in again.",
        )
    except Exception as e:
        logger.error(f"Session auth error: {e}")
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
