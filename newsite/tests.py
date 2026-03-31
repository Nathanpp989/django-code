from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.utils import timezone
from .models import NewLLM, ConvertLLM, LLMChoice, ChatMessage, ReverseLLM, LLMSummary
import json


# -------------------------
# Model Tests
# -------------------------

class NewLLMModelTest(TestCase):
    def setUp(self):
        self.llm = NewLLM.objects.create(llm_text="Test LLM")

    def test_str(self):
        self.assertEqual(str(self.llm), "Test LLM")

    def test_repr(self):
        self.assertIn("NewLLM", repr(self.llm))

    def test_was_published_recently(self):
        self.assertTrue(self.llm.was_published_recently())

    def test_was_published_recently_old(self):
        from datetime import timedelta
        self.llm.llm_date_used = timezone.now() - timedelta(days=2)
        self.llm.save()
        self.assertFalse(self.llm.was_published_recently())

    def test_ordering(self):
        llm2 = NewLLM.objects.create(llm_text="Test LLM 2")
        entries = list(NewLLM.objects.all())
        self.assertEqual(entries[0], llm2)


class LLMChoiceModelTest(TestCase):
    def setUp(self):
        self.llm = NewLLM.objects.create(llm_text="Test LLM")
        self.choice = LLMChoice.objects.create(
            new_llm=self.llm,
            choice_text="Option A",
            amount=0
        )

    def test_str(self):
        self.assertEqual(str(self.choice), "Option A")

    def test_default_amount(self):
        self.assertEqual(self.choice.amount, 0)

    def test_cascade_delete(self):
        self.llm.delete()
        self.assertEqual(LLMChoice.objects.filter(pk=self.choice.pk).count(), 0)


class ConvertLLMModelTest(TestCase):
    def setUp(self):
        self.obj = ConvertLLM.objects.create(
            new_string="hello", new_number=5
        )

    def test_str(self):
        self.assertEqual(str(self.obj), "hello")

    def test_str_empty(self):
        obj = ConvertLLM.objects.create(new_string="", new_number=0)
        self.assertIn("ConvertLLM", str(obj))

    def test_repr(self):
        self.assertIn("ConvertLLM", repr(self.obj))


class ReverseLLMModelTest(TestCase):
    def test_str_with_string(self):
        obj = ReverseLLM.objects.create(new_string="test", new_number=4)
        self.assertEqual(str(obj), "test")

    def test_str_without_string(self):
        obj = ReverseLLM.objects.create(new_number=4)
        self.assertIn("ReverseLLM", str(obj))


class ChatMessageModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser', password='testpass'
        )
        self.message = ChatMessage.objects.create(
            user=self.user,
            role="user",
            content="Hello AI"
        )

    def test_str(self):
        self.assertIn("testuser", str(self.message))

    def test_repr(self):
        self.assertIn("ChatMessage", repr(self.message))

    def test_cascade_delete(self):
        self.user.delete()
        self.assertEqual(
            ChatMessage.objects.filter(pk=self.message.pk).count(), 0
        )


class LLMSummaryModelTest(TestCase):
    def test_create_summary(self):
        summary = LLMSummary.objects.create(
            content_type="convert",
            object_id=1,
            prompt_hash="abc123",
            summary="Test summary",
            model_used="llama3"
        )
        self.assertEqual(str(summary), "Summary for convert #1")

    def test_unique_prompt_hash(self):
        LLMSummary.objects.create(
            content_type="convert",
            object_id=1,
            prompt_hash="unique_hash",
            summary="Test"
        )
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            LLMSummary.objects.create(
                content_type="convert",
                object_id=2,
                prompt_hash="unique_hash",
                summary="Duplicate"
            )


# -------------------------
# View Tests
# -------------------------

class AuthenticationTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.convert = ConvertLLM.objects.create(
            new_string="test", new_number=4
        )
        self.llm = NewLLM.objects.create(llm_text="Test")

    def test_convert_view_redirect(self):
        response = self.client.get(f'/convert/{self.convert.pk}/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response.url)

    def test_chat_view_redirect(self):
        response = self.client.get('/chat/')
        self.assertEqual(response.status_code, 302)

    def test_overview_view_redirect(self):
        response = self.client.get('/overview/')
        self.assertEqual(response.status_code, 302)

    def test_create_llm_redirect(self):
        response = self.client.get('/llm/create/')
        self.assertEqual(response.status_code, 302)


class IndexViewTest(TestCase):
    def test_index_loads(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)

    def test_index_shows_recent_entries(self):
        NewLLM.objects.create(llm_text="Test Entry")
        response = self.client.get('/')
        self.assertContains(response, "Test Entry")


class HealthCheckTest(TestCase):
    def test_health_check(self):
        response = self.client.get('/health/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["django"], "ok")
        self.assertEqual(data["database"], "ok")


class ConvertViewTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser', password='testpass'
        )
        self.client.login(username='testuser', password='testpass')
        self.obj = ConvertLLM.objects.create(
            new_string="hello", new_number=5
        )

    def test_get_view(self):
        response = self.client.get(f'/convert/{self.obj.pk}/')
        self.assertEqual(response.status_code, 200)

    def test_post_valid(self):
        response = self.client.post(
            f'/convert/{self.obj.pk}/',
            {"input_string": "new text"}
        )
        self.assertEqual(response.status_code, 302)
        self.obj.refresh_from_db()
        self.assertEqual(self.obj.new_string, "new text")
        self.assertEqual(self.obj.new_number, 8)

    def test_post_empty(self):
        response = self.client.post(
            f'/convert/{self.obj.pk}/',
            {"input_string": ""}
        )
        self.assertEqual(response.status_code, 200)

    def test_404_invalid_pk(self):
        response = self.client.get('/convert/99999/')
        self.assertEqual(response.status_code, 404)


class AmountViewTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser', password='testpass'
        )
        self.client.login(username='testuser', password='testpass')
        self.llm = NewLLM.objects.create(llm_text="Test LLM")
        self.choice = LLMChoice.objects.create(
            new_llm=self.llm,
            choice_text="Option A",
            amount=0
        )

    def test_valid_vote(self):
        response = self.client.post(
            f'/amount/{self.llm.pk}/',
            {"amount": self.choice.pk}
        )
        self.assertEqual(response.status_code, 302)
        self.choice.refresh_from_db()
        self.assertEqual(self.choice.amount, 1)

    def test_invalid_vote(self):
        response = self.client.post(
            f'/amount/{self.llm.pk}/',
            {"amount": "invalid"}
        )
        self.assertEqual(response.status_code, 200)

    def test_vote_invalidates_summary(self):
        LLMSummary.objects.create(
            content_type="results",
            object_id=self.llm.pk,
            prompt_hash="test_hash",
            summary="Old summary"
        )
        self.client.post(
            f'/amount/{self.llm.pk}/',
            {"amount": self.choice.pk}
        )
        self.assertEqual(
            LLMSummary.objects.filter(
                content_type="results",
                object_id=self.llm.pk
            ).count(), 0
        )


class CreateViewTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser', password='testpass'
        )
        self.client.login(username='testuser', password='testpass')

    def test_create_llm_get(self):
        response = self.client.get('/llm/create/')
        self.assertEqual(response.status_code, 200)

    def test_create_llm_post(self):
        response = self.client.post(
            '/llm/create/',
            {"llm_text": "New LLM", "choices": "Option A\nOption B"}
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(NewLLM.objects.filter(llm_text="New LLM").exists())
        self.assertEqual(
            LLMChoice.objects.filter(new_llm__llm_text="New LLM").count(), 2
        )

    def test_create_convert_get(self):
        response = self.client.get('/convert/create/')
        self.assertEqual(response.status_code, 200)

    def test_create_convert_post(self):
        response = self.client.post(
            '/convert/create/',
            {"input_string": "test string"}
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            ConvertLLM.objects.filter(new_string="test string").exists()
        )


class ChatViewTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser', password='testpass'
        )
        self.client.login(username='testuser', password='testpass')

    def test_chat_view_loads(self):
        response = self.client.get('/chat/')
        self.assertEqual(response.status_code, 200)

    def test_chat_message_empty(self):
        response = self.client.post(
            '/chat/message/',
            data=json.dumps({"message": ""}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 400)

    def test_chat_message_too_long(self):
        response = self.client.post(
            '/chat/message/',
            data=json.dumps({"message": "x" * 2001}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 400)

    def test_chat_message_invalid_json(self):
        response = self.client.post(
            '/chat/message/',
            data="not json",
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 400)

    def test_chat_clear(self):
        ChatMessage.objects.create(
            user=self.user, role="user", content="test"
        )
        response = self.client.post('/chat/clear/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            ChatMessage.objects.filter(user=self.user).count(), 0
        )

    def test_chat_export(self):
        ChatMessage.objects.create(
            user=self.user, role="user", content="test message"
        )
        response = self.client.get('/chat/export/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv')
        self.assertIn('chat_history.csv', response['Content-Disposition'])

    def test_chat_pagination(self):
        for i in range(60):
            ChatMessage.objects.create(
                user=self.user, role="user", content=f"Message {i}"
            )
        response = self.client.get('/chat/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['chat_history']), 50)

    def test_rate_limiting(self):
        from django.core.cache import cache
        cache.set(f"chat_rate_{self.user.pk}", 10, timeout=60)
        response = self.client.post(
            '/chat/message/',
            data=json.dumps({"message": "hello"}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 429)
        cache.delete(f"chat_rate_{self.user.pk}")
