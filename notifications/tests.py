from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.urls import reverse

from .models import Notification

User = get_user_model()


class NotificationScopeTests(TestCase):
    def setUp(self):
        self.a = User.objects.create_user(username='a', email='a@x.com', password='StrongPass123', role=User.Role.USER, library_card_id='C1')
        self.b = User.objects.create_user(username='b', email='b@x.com', password='StrongPass123', role=User.Role.USER, library_card_id='C2')
        self.na = Notification.objects.create(recipient=self.a, message='for a')
        self.nb = Notification.objects.create(recipient=self.b, message='for b')
        self.client_a = Client(); self.client_a.login(username='a', password='StrongPass123')

    def test_cannot_delete_other_users_notification(self):
        self.client_a.post(reverse('notifications:delete', args=[self.nb.pk]))
        self.assertTrue(Notification.objects.filter(pk=self.nb.pk).exists())

    def test_delete_own_and_clear_all_only_affect_self(self):
        self.client_a.post(reverse('notifications:delete', args=[self.na.pk]))
        self.assertFalse(Notification.objects.filter(pk=self.na.pk).exists())
        Notification.objects.create(recipient=self.a, message='another')
        self.client_a.post(reverse('notifications:clear_all'))
        self.assertEqual(Notification.objects.filter(recipient=self.a).count(), 0)
        self.assertEqual(Notification.objects.filter(recipient=self.b).count(), 1)
