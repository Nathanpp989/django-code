from django.test import TestCase

# Create your tests here.
from django.test import TestCase
from django.contrib.auth.models import User
from .models import ChatMessage
import json

class ChatViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass'
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

    def test_chat_clear(self):
        ChatMessage.objects.create(
            user=self.user,
            role="user",
            content="test message"
        )
        response = self.client.post('/chat/clear/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(ChatMessage.objects.filter(user=self.user).count(), 0)

    def test_unauthenticated_redirect(self):
        self.client.logout()
        response = self.client.get('/chat/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response.url)
