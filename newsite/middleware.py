"""
Client Certificate Middleware for Django LLM.
Verifies that requests through the mTLS NGINX server block
have a valid client certificate.

Add to MIDDLEWARE in settings.py after SecurityMiddleware:
    "django_llm.middleware.ClientCertificateMiddleware",
"""

from django.http import HttpResponseForbidden
from django.conf import settings
import logging

logger = logging.getLogger(__name__)

PUBLIC_PATHS = getattr(settings, "CLIENT_CERT_EXEMPT_PATHS", [
    "/accounts/login/",
    "/accounts/logout/",
    "/static/",
    "/media/",
    "/favicon.ico",
    "/robots.txt",
    "/admin/login/",
    "/health/",
])


class ClientCertificateMiddleware:
    """
    Verifies client certificates passed from NGINX via headers.
    Bypassed entirely in DEBUG mode so development works without certs.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if settings.DEBUG:
            return self.get_response(request)

        if any(request.path.startswith(path) for path in PUBLIC_PATHS):
            return self.get_response(request)

        cert_verify = request.META.get("HTTP_X_SSL_CLIENT_VERIFY", "NONE")
        cert_dn = request.META.get("HTTP_X_SSL_CLIENT_DN", "Unknown")

        if cert_verify != "SUCCESS":
            logger.warning(
                f"Client cert verification failed for {request.path}. "
                f"Status: {cert_verify}, "
                f"IP: {request.META.get('REMOTE_ADDR')}"
            )
            return HttpResponseForbidden(
                "Client certificate required. "
                "Please import your client certificate and try again."
            )

        request.client_cert_dn = cert_dn
        request.client_cert_verified = True
        logger.debug(f"Client cert verified for {request.path}: {cert_dn}")

        return self.get_response(request)
