"""
Tests for the FastAPI application.

Run with:
    pytest fastapi_app/tests/ -v

Or via Makefile:
    make test-fastapi
"""

import os
import sys
from fastapi.testclient import TestClient
from django.contrib.auth.models import User
from django.test import TestCase
from django_llm.models import NewLLM, ConvertLLM, LLMChoice, ChatMessage

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "newsite.settings")
if os.getcwd() not in sys.path:
    sys.path.insert(0, os.getcwd())

import django
django.setup()


# -------------------------
# Test Client Setup
# -------------------------

def get_test_client():
    """Get a FastAPI test client with a mocked authenticated session."""
    from fastapi_app.main import app
    return TestClient(app)


def get_auth_headers(client, username="testuser", password="testpass123!"):
    """
    Create a test user and return headers with a valid session cookie.
    Since we share Django sessions, we need to create a real Django session.
    """
    from django.contrib.sessions.backends.db import SessionStore

    # Create user if not exists
    user, _ = User.objects.get_or_create(username=username)
    user.set_password(password)
    user.save()

    # Create a Django session for this user
    session = SessionStore()
    session["_auth_user_id"] = str(user.pk)
    session["_auth_user_backend"] = "django.contrib.auth.backends.ModelBackend"
    session.save()

    return {"cookies": {"sessionid": session.session_key}, "user": user}


# -------------------------
# Health Tests
# -------------------------

class TestHealthEndpoint(TestCase):
    def setUp(self):
        self.client = get_test_client()

    def test_health_check(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["fastapi"], "ok")
        self.assertEqual(data["database"], "ok")

    def test_api_root(self):
        response = self.client.get("/api")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("docs", data)


# -------------------------
# Auth Tests
# -------------------------

class TestAuthentication(TestCase):
    def setUp(self):
        self.client = get_test_client()

    def test_no_session_returns_401(self):
        response = self.client.get("/api/llm/")
        self.assertEqual(response.status_code, 401)

    def test_invalid_session_returns_401(self):
        response = self.client.get(
            "/api/llm/",
            cookies={"sessionid": "invalidsession"}
        )
        self.assertEqual(response.status_code, 401)

    def test_valid_session_returns_200(self):
        auth = get_auth_headers(self.client)
        response = self.client.get(
            "/api/llm/",
            cookies={"sessionid": auth["cookies"]["sessionid"]}
        )
        self.assertEqual(response.status_code, 200)


# -------------------------
# LLM Entry Tests
# -------------------------

class TestLLMEndpoints(TestCase):
    def setUp(self):
        self.client = get_test_client()
        auth = get_auth_headers(self.client)
        self.session_cookie = auth["cookies"]["sessionid"]
        self.user = auth["user"]
        self.llm = NewLLM.objects.create(llm_text="Test LLM")
        self.choice = LLMChoice.objects.create(
            new_llm=self.llm,
            choice_text="Option A",
            amount=0
        )

    def test_list_llm_entries(self):
        response = self.client.get(
            "/api/llm/",
            cookies={"sessionid": self.session_cookie}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("results", data)
        self.assertIn("count", data)

    def test_create_llm_entry(self):
        response = self.client.post(
            "/api/llm/",
            json={"llm_text": "New Entry", "choices": ["A", "B"]},
            cookies={"sessionid": self.session_cookie}
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["llm_text"], "New Entry")
        self.assertEqual(len(data["choices"]), 2)

    def test_get_llm_entry(self):
        response = self.client.get(
            f"/api/llm/{self.llm.pk}",
            cookies={"sessionid": self.session_cookie}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["llm_text"], "Test LLM")

    def test_get_nonexistent_llm(self):
        response = self.client.get(
            "/api/llm/99999",
            cookies={"sessionid": self.session_cookie}
        )
        self.assertEqual(response.status_code, 404)

    def test_update_llm_entry(self):
        response = self.client.patch(
            f"/api/llm/{self.llm.pk}",
            json={"llm_text": "Updated Text"},
            cookies={"sessionid": self.session_cookie}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["llm_text"], "Updated Text")

    def test_delete_llm_entry(self):
        llm = NewLLM.objects.create(llm_text="To Delete")
        response = self.client.delete(
            f"/api/llm/{llm.pk}",
            cookies={"sessionid": self.session_cookie}
        )
        self.assertEqual(response.status_code, 204)
        self.assertFalse(NewLLM.objects.filter(pk=llm.pk).exists())

    def test_vote_for_choice(self):
        response = self.client.post(
            f"/api/llm/{self.llm.pk}/vote",
            json={"choice_id": self.choice.pk},
            cookies={"sessionid": self.session_cookie}
        )
        self.assertEqual(response.status_code, 200)
        self.choice.refresh_from_db()
        self.assertEqual(self.choice.amount, 1)

    def test_vote_invalid_choice(self):
        response = self.client.post(
            f"/api/llm/{self.llm.pk}/vote",
            json={"choice_id": 99999},
            cookies={"sessionid": self.session_cookie}
        )
        self.assertEqual(response.status_code, 404)

    def test_get_voting_results(self):
        response = self.client.get(
            f"/api/llm/{self.llm.pk}/results",
            cookies={"sessionid": self.session_cookie}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("total_votes", data)
        self.assertIn("choices", data)

    def test_search_llm_entries(self):
        response = self.client.get(
            "/api/llm/?search=Test",
            cookies={"sessionid": self.session_cookie}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertGreater(data["count"], 0)

    def test_pagination(self):
        for i in range(25):
            NewLLM.objects.create(llm_text=f"Entry {i}")
        response = self.client.get(
            "/api/llm/?page=1&page_size=10",
            cookies={"sessionid": self.session_cookie}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["results"]), 10)


# -------------------------
# Convert Tests
# -------------------------

class TestConvertEndpoints(TestCase):
    def setUp(self):
        self.client = get_test_client()
        auth = get_auth_headers(self.client)
        self.session_cookie = auth["cookies"]["sessionid"]
        self.convert = ConvertLLM.objects.create(
            new_string="hello", new_number=5
        )

    def test_list_conversions(self):
        response = self.client.get(
            "/api/convert/",
            cookies={"sessionid": self.session_cookie}
        )
        self.assertEqual(response.status_code, 200)

    def test_create_conversion(self):
        response = self.client.post(
            "/api/convert/",
            json={"input_string": "test string"},
            cookies={"sessionid": self.session_cookie}
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["new_string"], "test string")
        self.assertEqual(data["new_number"], 11)

    def test_get_conversion(self):
        response = self.client.get(
            f"/api/convert/{self.convert.pk}",
            cookies={"sessionid": self.session_cookie}
        )
        self.assertEqual(response.status_code, 200)

    def test_update_conversion(self):
        response = self.client.patch(
            f"/api/convert/{self.convert.pk}",
            json={"input_string": "updated string"},
            cookies={"sessionid": self.session_cookie}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["new_string"], "updated string")

    def test_delete_conversion(self):
        c = ConvertLLM.objects.create(new_string="delete me", new_number=9)
        response = self.client.delete(
            f"/api/convert/{c.pk}",
            cookies={"sessionid": self.session_cookie}
        )
        self.assertEqual(response.status_code, 204)
        self.assertFalse(ConvertLLM.objects.filter(pk=c.pk).exists())

    def test_conversion_stats(self):
        response = self.client.get(
            "/api/convert/stats",
            cookies={"sessionid": self.session_cookie}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("total_conversions", data)
        self.assertIn("average_character_count", data)


# -------------------------
# Chat Tests
# -------------------------

class TestChatEndpoints(TestCase):
    def setUp(self):
        self.client = get_test_client()
        auth = get_auth_headers(self.client)
        self.session_cookie = auth["cookies"]["sessionid"]
        self.user = auth["user"]

    def test_get_chat_history_empty(self):
        response = self.client.get(
            "/api/chat/",
            cookies={"sessionid": self.session_cookie}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["count"], 0)

    def test_get_chat_stats(self):
        response = self.client.get(
            "/api/chat/stats",
            cookies={"sessionid": self.session_cookie}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("total_messages", data)

    def test_clear_chat_history(self):
        ChatMessage.objects.create(
            user=self.user, role="user", content="test"
        )
        response = self.client.delete(
            "/api/chat/",
            cookies={"sessionid": self.session_cookie}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            ChatMessage.objects.filter(user=self.user).count(), 0
        )
