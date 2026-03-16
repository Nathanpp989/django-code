"""
Client Certificate Middleware for Django LLM.
Verifies that requests coming through the mTLS NGINX server block
have a valid client certificate.

Add to settings.py MIDDLEWARE:
    "django_llm.middleware.ClientCertificateMiddleware",

Make sure it comes AFTER SecurityMiddleware but BEFORE AuthenticationMiddleware:
    MIDDLEWARE = [
        "django.middleware.security.SecurityMiddleware",
        "whitenoise.middleware.WhiteNoiseMiddleware",
        "django_llm.middleware.ClientCertificateMiddleware",  # Add here
        "django.contrib.sessions.middleware.SessionMiddleware",
        ...
    ]
"""

from django.http import HttpResponseForbidden
from django.conf import settings
import logging

logger = logging.getLogger(__name__)

# Routes that do NOT require a client certificate
# Login and static files should always be accessible
PUBLIC_PATHS = getattr(settings, "CLIENT_CERT_EXEMPT_PATHS", [
    "/accounts/login/",
    "/accounts/logout/",
    "/static/",
    "/media/",
    "/favicon.ico",
    "/robots.txt",
    "/admin/login/",
])


class ClientCertificateMiddleware:
    """
    Middleware that verifies client certificates passed from NGINX.
    NGINX sets X-SSL-Client-Verify header to 'SUCCESS' when the
    client presents a valid certificate signed by our CA.

    In development (DEBUG=True), this middleware is bypassed entirely
    so you can test without certificates.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Skip cert verification in development
        if settings.DEBUG:
            return self.get_response(request)

        # Skip cert verification for public paths
        if any(request.path.startswith(path) for path in PUBLIC_PATHS):
            return self.get_response(request)

        # Check client certificate verification status from NGINX header
        cert_verify = request.META.get("HTTP_X_SSL_CLIENT_VERIFY", "NONE")
        cert_dn = request.META.get("HTTP_X_SSL_CLIENT_DN", "Unknown")

        if cert_verify != "SUCCESS":
            logger.warning(
                f"Client certificate verification failed for {request.path}. "
                f"Status: {cert_verify}, IP: {request.META.get('REMOTE_ADDR')}"
            )
            return HttpResponseForbidden(
                "Client certificate required. "
                "Please import your client certificate and try again."
            )

        # Attach cert info to request for use in views if needed
        request.client_cert_dn = cert_dn
        request.client_cert_verified = True

        logger.debug(f"Client cert verified for {request.path}: {cert_dn}")

        return self.get_response(request)
