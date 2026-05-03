"""
Basic tests for FastAPI authentication and core functionality.
Run with: python -m pytest fastapi_app/tests.py -v
"""

import os
import django
from django.conf import settings

# Configure Django settings for tests
if not settings.configured:
    settings.configure(
        DEBUG=True,
        DATABASES={
            'default': {
                'ENGINE': 'django.db.backends.sqlite3',
                'NAME': ':memory:',
            }
        },
        INSTALLED_APPS=[
            'django.contrib.auth',
            'django.contrib.contenttypes',
            'django.contrib.sessions',
            'django_llm',
        ],
        SECRET_KEY='test-secret-key',
        USE_TZ=True,
        SESSION_ENGINE='django.contrib.sessions.backends.db',
        MIDDLEWARE=[
            'django.contrib.sessions.middleware.SessionMiddleware',
            'django.contrib.auth.middleware.AuthenticationMiddleware',
        ],
        ROOT_URLCONF='newsite.urls',
    )
    django.setup()

import pytest
from django.test import TestCase
from django.contrib.auth.models import User
from django.test.client import Client
from fastapi.testclient import TestClient
from fastapi_app.main import app
from fastapi_app.auth import get_current_user
from unittest.mock import Mock, patch


class FastAPIAuthTests(TestCase):
    """Test FastAPI authentication integration."""

    def setUp(self):
        self.client = Client()
        self.fastapi_client = TestClient(app)
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',
            email='test@example.com'
        )

    def test_session_auth_success(self):
        """Test that Django session authentication works in FastAPI."""
        # Login via Django
        self.client.login(username='testuser', password='testpass123')

        # Get session cookie
        session_cookie = self.client.cookies.get('sessionid')
        self.assertIsNotNone(session_cookie)

        # Test FastAPI endpoint with session cookie
        response = self.fastapi_client.get(
            '/api/health',
            cookies={'sessionid': session_cookie.value}
        )
        self.assertEqual(response.status_code, 200)

    def test_session_auth_failure_no_session(self):
        """Test that requests without session are rejected."""
        response = self.fastapi_client.get('/api/health')
        self.assertEqual(response.status_code, 401)

    def test_session_auth_failure_invalid_session(self):
        """Test that invalid sessions are rejected."""
        response = self.fastapi_client.get(
            '/api/health',
            cookies={'sessionid': 'invalid_session_id'}
        )
        self.assertEqual(response.status_code, 401)

    def test_brute_force_detection(self):
        """Test that brute force attempts are blocked."""
        # Make multiple failed auth attempts
        for _ in range(6):  # More than BRUTE_FORCE_THRESHOLD
            response = self.fastapi_client.get(
                '/api/health',
                cookies={'sessionid': 'invalid_session_id'}
            )
            if response.status_code == 429:
                break

        # Should eventually get rate limited
        response = self.fastapi_client.get(
            '/api/health',
            cookies={'sessionid': 'invalid_session_id'}
        )
        self.assertEqual(response.status_code, 429)


class FastAPIRouterTests(TestCase):
    """Test FastAPI router functionality."""

    def setUp(self):
        self.client = Client()
        self.fastapi_client = TestClient(app)
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        # Login and get session cookie
        self.client.login(username='testuser', password='testpass123')
        self.session_cookie = self.client.cookies.get('sessionid')

    def test_health_endpoint(self):
        """Test health check endpoint."""
        response = self.fastapi_client.get('/api/health')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('fastapi', data)
        self.assertIn('database', data)

    def test_metrics_endpoint_rate_limited(self):
        """Test that metrics endpoint is rate limited."""
        # Make multiple requests to metrics endpoint
        for _ in range(15):  # More than rate limit
            response = self.fastapi_client.get(
                '/api/metrics',
                cookies={'sessionid': self.session_cookie.value}
            )
            if response.status_code == 429:
                break

        # Should eventually get rate limited
        response = self.fastapi_client.get(
            '/api/metrics',
            cookies={'sessionid': self.session_cookie.value}
        )
        self.assertEqual(response.status_code, 429)


class SchemaValidationTests(TestCase):
    """Test Pydantic schema validation."""

    def test_new_llm_create_validation(self):
        """Test NewLLMCreate schema validation."""
        from fastapi_app.schemas import NewLLMCreate

        # Valid input
        schema = NewLLMCreate(llm_text="Test LLM", choices=["Choice 1", "Choice 2"])
        self.assertEqual(schema.llm_text, "Test LLM")
        self.assertEqual(len(schema.choices), 2)

        # Invalid: empty text
        with self.assertRaises(ValueError):
            NewLLMCreate(llm_text="", choices=["Choice 1"])

        # Invalid: text too long
        with self.assertRaises(ValueError):
            NewLLMCreate(llm_text="x" * 201, choices=["Choice 1"])

        # Invalid: empty choice
        with self.assertRaises(ValueError):
            NewLLMCreate(llm_text="Test", choices=["", "Valid choice"])

    def test_html_sanitization(self):
        """Test that HTML/script tags are sanitized."""
        from fastapi_app.schemas import NewLLMCreate

        # Input with script tag
        schema = NewLLMCreate(
            llm_text='Test <script>alert("xss")</script> text',
            choices=['Choice <img src=x onerror=alert(1)>']
        )

        # Should be sanitized
        self.assertNotIn('<script>', schema.llm_text)
        self.assertNotIn('<img', schema.choices[0])


if __name__ == '__main__':
    pytest.main([__file__, '-v'])