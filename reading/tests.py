from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from books.models import Book
from notifications.models import Notification
from .models import ReadingSession, Highlight

User = get_user_model()


class ReadingSessionTests(TestCase):
    def setUp(self):
        self.user_a = User.objects.create_user(
            username='reader_a', email='a@example.com', password='StrongPass123',
            role=User.Role.USER, library_card_id='CARD200',
        )
        self.book = Book.objects.create(
            title='Sample Book', author='Author', publication_year=2020,
            total_copies=1, available_copies=1, content_text='<p>Python is a programming language.</p>',
        )

    def test_only_one_active_session_per_user_book(self):
        ReadingSession.objects.create(user=self.user_a, book=self.book)
        with self.assertRaises(Exception):
            ReadingSession.objects.create(user=self.user_a, book=self.book)

    def test_start_session_resumes_recent_session(self):
        client = Client()
        client.login(username='a@example.com', password='StrongPass123')
        url = reverse('reading:session_start', args=[self.book.pk])
        first = client.post(url).json()
        second = client.post(url).json()
        self.assertEqual(first['session_id'], second['session_id'])
        self.assertTrue(second['resumed'])

    def test_new_session_created_after_stale_session(self):
        session = ReadingSession.objects.create(user=self.user_a, book=self.book)
        session.last_heartbeat_at = timezone.now() - timezone.timedelta(minutes=10)
        session.save()

        client = Client()
        client.login(username='a@example.com', password='StrongPass123')
        data = client.post(reverse('reading:session_start', args=[self.book.pk])).json()

        session.refresh_from_db()
        self.assertIsNotNone(session.ended_at)
        self.assertNotEqual(data['session_id'], session.id)

    def test_stop_reading_creates_notification_and_finalizes_session(self):
        client = Client()
        client.login(username='a@example.com', password='StrongPass123')
        start_data = client.post(reverse('reading:session_start', args=[self.book.pk])).json()
        session_id = start_data['session_id']

        client.post(reverse('reading:session_end', args=[session_id]))
        session = ReadingSession.objects.get(pk=session_id)
        self.assertIsNotNone(session.ended_at)
        self.assertTrue(
            Notification.objects.filter(recipient=self.user_a, message__icontains='stopped reading').exists()
        )

    def test_update_position_is_saved(self):
        client = Client()
        client.login(username='a@example.com', password='StrongPass123')
        start_data = client.post(reverse('reading:session_start', args=[self.book.pk])).json()
        session_id = start_data['session_id']

        client.post(reverse('reading:session_position', args=[session_id]), data='{"position": 7}', content_type='application/json')
        session = ReadingSession.objects.get(pk=session_id)
        self.assertEqual(session.last_position, 7)


class HighlightSecurityTests(TestCase):
    def setUp(self):
        self.user_a = User.objects.create_user(
            username='hl_a', email='hla@example.com', password='StrongPass123',
            role=User.Role.USER, library_card_id='CARD300',
        )
        self.user_b = User.objects.create_user(
            username='hl_b', email='hlb@example.com', password='StrongPass123',
            role=User.Role.USER, library_card_id='CARD301',
        )
        self.book = Book.objects.create(
            title='Highlight Book', author='Author', publication_year=2021,
            total_copies=1, available_copies=1, content_text='<p>Python is a programming language.</p>',
        )
        self.highlight = Highlight.objects.create(
            user=self.user_a, book=self.book, selected_text='Python', start_offset=0, end_offset=6, color='yellow',
        )

    def test_user_b_cannot_see_user_a_highlight(self):
        client = Client()
        client.login(username='hlb@example.com', password='StrongPass123')
        response = client.get(reverse('reading:highlight_list', args=[self.book.pk]))
        self.assertEqual(response.json()['highlights'], [])

    def test_user_b_cannot_delete_user_a_highlight(self):
        client = Client()
        client.login(username='hlb@example.com', password='StrongPass123')
        response = client.post(reverse('reading:highlight_delete', args=[self.highlight.pk]))
        self.assertEqual(response.status_code, 404)
        self.assertTrue(Highlight.objects.filter(pk=self.highlight.pk).exists())


class PDFStreamAccessTests(TestCase):
    """Unauthorized/unauthenticated requests must not be able to pull PDF content."""

    def test_anonymous_user_cannot_stream_pdf(self):
        user = User.objects.create_user(
            username='owner', email='owner@example.com', password='StrongPass123',
            role=User.Role.USER, library_card_id='CARD400',
        )
        book = Book.objects.create(title='PDF Book', author='Author', publication_year=2022, total_copies=1, available_copies=1)
        client = Client()
        response = client.get(reverse('reading:pdf_stream', args=[book.pk]))
        self.assertIn(response.status_code, (302, 403))  # redirected to login, not served


class RoleAndResumeTests(TestCase):
    def setUp(self):
        self.member = User.objects.create_user(username='rm', email='rm@x.com', password='StrongPass123', role=User.Role.USER, library_card_id='CARD500')
        self.lib = User.objects.create_user(username='rl', email='rl@x.com', password='StrongPass123', role=User.Role.LIBRARIAN, employee_id='E500')
        self.book = Book.objects.create(title='T', author='A', publication_year=2020, total_copies=1, available_copies=1, content_text='<p>x</p>')

    def test_staff_get_no_session(self):
        c = Client(); c.login(username='rl', password='StrongPass123')
        data = c.post(reverse('reading:session_start', args=[self.book.pk])).json()
        self.assertIsNone(data['session_id'])
        self.assertEqual(ReadingSession.objects.count(), 0)

    def test_last_position_restored_on_reopen(self):
        c = Client(); c.login(username='rm', password='StrongPass123')
        sid = c.post(reverse('reading:session_start', args=[self.book.pk])).json()['session_id']
        c.post(reverse('reading:session_position', args=[sid]), data='{"position": 12}', content_type='application/json')
        c.post(reverse('reading:session_end', args=[sid]))
        response = c.get(reverse('reading:reader', args=[self.book.pk]))
        self.assertEqual(response.context['resume_position'], 12)

    def test_stop_reading_only_affects_own_session(self):
        other = User.objects.create_user(username='ro', email='ro@x.com', password='StrongPass123', role=User.Role.USER, library_card_id='CARD501')
        s = ReadingSession.objects.create(user=other, book=self.book)
        c = Client(); c.login(username='rm', password='StrongPass123')
        c.post(reverse('reading:stop_reading', args=[self.book.pk]))
        s.refresh_from_db()
        self.assertIsNone(s.ended_at)


import tempfile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class PdfRangeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='pr', email='pr@x.com', password='StrongPass123', role=User.Role.USER, library_card_id='CARD700')
        self.payload = b'%PDF-1.4\n' + bytes(range(256)) * 4
        self.book = Book.objects.create(title='P', author='A', publication_year=2020, total_copies=1, available_copies=1,
                                        book_file=SimpleUploadedFile('p.pdf', self.payload, content_type='application/pdf'))
        self.c = Client(); self.c.login(username='pr', password='StrongPass123')
        self.url = reverse('reading:pdf_stream', args=[self.book.pk])

    def test_full_response_advertises_ranges(self):
        r = self.c.get(self.url)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Accept-Ranges'], 'bytes')
        self.assertEqual(int(r['Content-Length']), len(self.payload))

    def test_partial_content(self):
        r = self.c.get(self.url, HTTP_RANGE='bytes=0-9')
        self.assertEqual(r.status_code, 206)
        self.assertEqual(r['Content-Range'], f'bytes 0-9/{len(self.payload)}')
        self.assertEqual(b''.join(r.streaming_content), self.payload[:10])

    def test_suffix_and_open_ended_ranges(self):
        r = self.c.get(self.url, HTTP_RANGE='bytes=-16')
        self.assertEqual(b''.join(r.streaming_content), self.payload[-16:])
        r = self.c.get(self.url, HTTP_RANGE=f'bytes={len(self.payload) - 4}-')
        self.assertEqual(b''.join(r.streaming_content), self.payload[-4:])

    def test_unsatisfiable_range_and_login_required(self):
        self.assertEqual(self.c.get(self.url, HTTP_RANGE='bytes=99999-100000').status_code, 416)
        self.assertEqual(Client().get(self.url).status_code, 302)
