from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from .models import PasswordResetOTP

User = get_user_model()


class RoleBasedAccessTests(TestCase):
    """Users must never be able to reach Admin/Librarian pages by URL alone,
    and an Admin/Librarian account must never show up in the normal-user list."""

    def setUp(self):
        self.admin = User.objects.create_user(
            username='admin1', email='admin1@example.com', password='StrongPass123',
            role=User.Role.ADMIN, is_staff=True,
        )
        self.librarian = User.objects.create_user(
            username='lib1', email='lib1@example.com', password='StrongPass123',
            role=User.Role.LIBRARIAN, employee_id='EMP001',
        )
        self.member = User.objects.create_user(
            username='user1', email='user1@example.com', password='StrongPass123',
            role=User.Role.USER, library_card_id='CARD001',
        )

    def test_member_cannot_access_admin_dashboard(self):
        client = Client()
        client.login(username='user1', password='StrongPass123')
        self.assertEqual(client.get(reverse('accounts:admin_dashboard')).status_code, 403)

    def test_member_cannot_access_librarian_dashboard(self):
        client = Client()
        client.login(username='user1', password='StrongPass123')
        self.assertEqual(client.get(reverse('accounts:librarian_dashboard')).status_code, 403)

    def test_admin_does_not_appear_in_user_list(self):
        client = Client()
        client.login(username='admin1', password='StrongPass123')
        response = client.get(reverse('accounts:user_list'))
        usernames = [u.username for u in response.context['page_obj']]
        self.assertNotIn('admin1', usernames)
        self.assertNotIn('lib1', usernames)
        self.assertIn('user1', usernames)

    def test_admin_does_not_appear_in_librarian_list(self):
        client = Client()
        client.login(username='admin1', password='StrongPass123')
        response = client.get(reverse('accounts:librarian_list'))
        usernames = [u.username for u in response.context['page_obj']]
        self.assertNotIn('admin1', usernames)
        self.assertIn('lib1', usernames)


class MultiFieldLoginTests(TestCase):
    def setUp(self):
        self.member = User.objects.create_user(
            username='user2', email='user2@example.com', password='StrongPass123',
            role=User.Role.USER, library_card_id='CARD002', phone_number='+15551234567',
        )

    def test_login_with_email(self):
        self.assertTrue(Client().login(username='user2@example.com', password='StrongPass123'))

    def test_login_with_library_card_id(self):
        self.assertTrue(Client().login(username='CARD002', password='StrongPass123'))

    def test_inactive_user_cannot_login(self):
        self.member.is_active = False
        self.member.save()
        self.assertFalse(Client().login(username='user2@example.com', password='StrongPass123'))


class OTPPasswordResetTests(TestCase):
    def setUp(self):
        self.member = User.objects.create_user(
            username='reset1', email='reset1@example.com', password='OldPass123',
            role=User.Role.USER, library_card_id='CARD900',
        )

    def test_forgot_password_issues_otp_for_existing_email(self):
        client = Client()
        client.post(reverse('accounts:forgot_password'), {'email': 'reset1@example.com'})
        self.assertEqual(PasswordResetOTP.objects.filter(user=self.member).count(), 1)

    def test_forgot_password_does_not_leak_nonexistent_email(self):
        client = Client()
        response = client.post(reverse('accounts:forgot_password'), {'email': 'doesnotexist@example.com'}, follow=True)
        # Same generic message regardless of whether the account exists.
        self.assertContains(response, "verification code has been sent")
        self.assertEqual(PasswordResetOTP.objects.count(), 0)

    def test_correct_otp_allows_password_reset(self):
        client = Client()
        client.post(reverse('accounts:forgot_password'), {'email': 'reset1@example.com'})
        otp = PasswordResetOTP.objects.get(user=self.member)

        response = client.post(reverse('accounts:verify_otp'), {'otp_code': otp.code})
        self.assertRedirects(response, reverse('accounts:set_new_password'))

        client.post(reverse('accounts:set_new_password'), {
            'new_password': 'BrandNewPass123', 'confirm_password': 'BrandNewPass123',
        })
        self.member.refresh_from_db()
        self.assertTrue(self.member.check_password('BrandNewPass123'))

    def test_wrong_otp_is_rejected(self):
        client = Client()
        client.post(reverse('accounts:forgot_password'), {'email': 'reset1@example.com'})
        response = client.post(reverse('accounts:verify_otp'), {'otp_code': '000000'}, follow=True)
        self.assertContains(response, "Invalid verification code")
        self.member.refresh_from_db()
        self.assertTrue(self.member.check_password('OldPass123'))  # unchanged

    def test_expired_otp_is_rejected(self):
        client = Client()
        client.post(reverse('accounts:forgot_password'), {'email': 'reset1@example.com'})
        otp = PasswordResetOTP.objects.get(user=self.member)
        otp.expires_at = timezone.now() - timezone.timedelta(minutes=1)
        otp.save()

        response = client.post(reverse('accounts:verify_otp'), {'otp_code': otp.code}, follow=True)
        self.assertContains(response, "expired")

    def test_otp_cannot_be_reused(self):
        client = Client()
        client.post(reverse('accounts:forgot_password'), {'email': 'reset1@example.com'})
        otp = PasswordResetOTP.objects.get(user=self.member)
        client.post(reverse('accounts:verify_otp'), {'otp_code': otp.code})
        client.post(reverse('accounts:set_new_password'), {
            'new_password': 'FirstReset123', 'confirm_password': 'FirstReset123',
        })

        # Try to reuse the same (now-used) OTP again on a fresh session.
        client2 = Client()
        session = client2.session
        session['otp_reset_email'] = 'reset1@example.com'
        session['otp_reset_user_id'] = self.member.pk
        session.save()
        response = client2.post(reverse('accounts:verify_otp'), {'otp_code': otp.code}, follow=True)
        self.assertContains(response, "expired")

    def test_brute_force_attempts_are_throttled(self):
        client = Client()
        client.post(reverse('accounts:forgot_password'), {'email': 'reset1@example.com'})
        for _ in range(6):
            client.post(reverse('accounts:verify_otp'), {'otp_code': '999999'})
        otp = PasswordResetOTP.objects.get(user=self.member)
        self.assertTrue(otp.is_used)  # locked out after too many wrong attempts


# ---------------------------------------------------------------
# OTP e-mail delivery
# ---------------------------------------------------------------
from unittest import mock

from django.core import mail
from django.db import DatabaseError
from django.test import override_settings


class OTPEmailDeliveryTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='fp', email='fp@example.com', password='StrongPass123',
                                             role=User.Role.USER, library_card_id='CARD600')
        self.url = reverse('accounts:forgot_password')

    def test_otp_is_emailed_to_registered_address_case_insensitively(self):
        self.client.post(self.url, {'email': 'FP@example.com'})
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['fp@example.com'])
        self.assertRegex(mail.outbox[0].body, r'\b\d{6}\b')

    def test_same_message_for_registered_and_unknown_and_no_mail_for_unknown(self):
        a = self.client.post(self.url, {'email': 'fp@example.com'}, follow=True)
        b = self.client.post(self.url, {'email': 'nobody@example.com'}, follow=True)
        for r in (a, b):
            self.assertContains(r, "If that email is registered, a verification code has been sent to it.")
        self.assertEqual(len(mail.outbox), 1)

    def test_delivery_failure_shows_error_and_retry_works_immediately(self):
        with mock.patch('accounts.views.send_mail', side_effect=OSError('smtp down')):
            with self.assertLogs('library', level='ERROR'):
                r = self.client.post(self.url, {'email': 'fp@example.com'})
        self.assertEqual(r.status_code, 200)                       # stays on the form
        self.assertContains(r, "send the verification code right now")
        self.assertNotContains(r, 'smtp down')                      # technical detail never shown
        self.assertEqual(PasswordResetOTP.objects.count(), 0)       # no cooldown consumed
        r = self.client.post(self.url, {'email': 'fp@example.com'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.smtp.EmailBackend', EMAIL_HOST_USER='', EMAIL_HOST_PASSWORD='')
    def test_missing_smtp_credentials_gives_friendly_error(self):
        with self.assertLogs('library', level='ERROR'):
            r = self.client.post(self.url, {'email': 'fp@example.com'})
        self.assertContains(r, "send the verification code right now")
        self.assertEqual(PasswordResetOTP.objects.count(), 0)

    def test_code_never_in_response_or_logs(self):
        with self.assertLogs('library', level='INFO') as logs:
            r = self.client.post(self.url, {'email': 'fp@example.com'}, follow=True)
        code = PasswordResetOTP.objects.get().code
        self.assertNotContains(r, code)
        self.assertFalse(any(code in line for line in logs.output))

    def test_forgot_password_cooldown_blocks_mail_bombing(self):
        self.client.post(self.url, {'email': 'fp@example.com'})
        self.client.post(self.url, {'email': 'fp@example.com'})
        self.assertEqual(len(mail.outbox), 1)

    def test_failed_resend_keeps_previous_code_valid(self):
        self.client.post(self.url, {'email': 'fp@example.com'})
        PasswordResetOTP.objects.update(created_at=timezone.now() - timezone.timedelta(minutes=5))
        with mock.patch('accounts.views.send_mail', side_effect=OSError('down')):
            r = self.client.post(reverse('accounts:resend_otp'), follow=True)
        self.assertContains(r, "send a new code right now")
        self.assertEqual(PasswordResetOTP.objects.filter(is_used=False).count(), 1)

    def test_successful_resend_invalidates_old_code(self):
        self.client.post(self.url, {'email': 'fp@example.com'})
        PasswordResetOTP.objects.update(created_at=timezone.now() - timezone.timedelta(minutes=5))
        self.client.post(reverse('accounts:resend_otp'))
        self.assertEqual(PasswordResetOTP.objects.filter(is_used=False).count(), 1)
        self.assertEqual(len(mail.outbox), 2)


# ---------------------------------------------------------------
# Staff search fields never show Django error pages
# ---------------------------------------------------------------
class StaffSearchRobustnessTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username='ad', email='ad@x.com', password='StrongPass123', role=User.Role.ADMIN, employee_id='A1')
        self.client.login(username='ad', password='StrongPass123')

    def test_weird_queries_return_200(self):
        for name in ('accounts:user_list', 'accounts:librarian_list'):
            for q in ('%00', 'a' * 5000, "'; DROP TABLE x;--", '%', '_', '\u202e\u0000'):
                r = self.client.get(reverse(name), {'q': q, 'page': 'abc'})
                self.assertEqual(r.status_code, 200, (name, q))

    def test_database_error_becomes_friendly_message(self):
        with mock.patch('django.core.paginator.Paginator.get_page', side_effect=DatabaseError('boom: secret table')):
            with self.assertLogs('library', level='ERROR'):
                r = self.client.get(reverse('accounts:user_list'), {'q': 'x'})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "couldn&#x27;t complete that search")
        self.assertNotContains(r, 'secret table')
