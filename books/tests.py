from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.urls import reverse

from .models import Book

User = get_user_model()


class BookCatalogueTests(TestCase):
    def setUp(self):
        self.member = User.objects.create_user(
            username='reader1', email='reader1@example.com', password='StrongPass123',
            role=User.Role.USER, library_card_id='CARD100',
        )
        Book.objects.create(title='Zebra Tales', author='A. Zed', publication_year=2010, total_copies=2, available_copies=2)
        Book.objects.create(title='Apple Stories', author='B. Young', publication_year=2015, total_copies=1, available_copies=0)

    def test_books_listed_alphabetically(self):
        client = Client()
        client.login(username='reader1@example.com', password='StrongPass123')
        response = client.get(reverse('books:list'))
        titles = [b.title for b in response.context['page_obj']]
        self.assertEqual(titles, sorted(titles))

    def test_availability_filter(self):
        client = Client()
        client.login(username='reader1@example.com', password='StrongPass123')
        response = client.get(reverse('books:search'), {'availability': 'AVAILABLE'})
        titles = [b.title for b in response.context['page_obj']]
        self.assertIn('Zebra Tales', titles)
        self.assertNotIn('Apple Stories', titles)


class BookRequestTests(TestCase):
    def setUp(self):
        self.member = User.objects.create_user(username='req', email='req@x.com', password='StrongPass123', role=User.Role.USER, library_card_id='CARD900')
        self.lib = User.objects.create_user(username='lib', email='lib@x.com', password='StrongPass123', role=User.Role.LIBRARIAN, employee_id='E900')

    def test_request_requires_title_author_year(self):
        from .models import BookRequest
        c = Client(); c.login(username='req', password='StrongPass123')
        c.post(reverse('books:request_book'), {'requested_title': 'Only Title'})
        self.assertEqual(BookRequest.objects.count(), 0)
        c.post(reverse('books:request_book'), {'requested_title': 'Dune', 'requested_author': 'Frank Herbert', 'requested_year': 1965})
        self.assertEqual(BookRequest.objects.count(), 1)

    def test_requester_notified_when_book_added(self):
        from .models import BookRequest
        from notifications.models import Notification
        BookRequest.objects.create(user=self.member, requested_title='Dune', requested_author='Frank Herbert', requested_year=1965)
        c = Client(); c.login(username='lib', password='StrongPass123')
        c.post(reverse('books:create'), {'title': 'dune', 'author': 'Frank Herbert', 'publication_year': 1965,
                                         'total_copies': 1, 'available_copies': 1, 'status': 'AVAILABLE'})
        self.assertTrue(Notification.objects.filter(recipient=self.member, message__icontains='now available').exists())
        self.assertEqual(BookRequest.objects.get().status, BookRequest.Status.FULFILLED)


class ListingPerformanceTests(TestCase):
    def test_book_list_query_count_is_constant(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        user = User.objects.create_user(username='perf', email='perf@x.com', password='StrongPass123', role=User.Role.USER, library_card_id='CARD800')
        for i in range(12):
            Book.objects.create(title=f'Book {i}', author='A', publication_year=2000, total_copies=1, available_copies=1,
                                content_text='<p>' + 'x' * 5000 + '</p>')
        c = Client(); c.login(username='perf', password='StrongPass123')
        with CaptureQueriesContext(connection) as ctx:
            response = c.get(reverse('books:list'))
        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(len(ctx), 10, [q['sql'][:80] for q in ctx])   # no per-book queries (no N+1)


from unittest import mock

from django.db import DatabaseError
from django.test import override_settings


class BookSearchRobustnessTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='sr', email='sr@x.com', password='StrongPass123', role=User.Role.USER, library_card_id='CARD950')
        Book.objects.create(title='Dune', author='Frank Herbert', publication_year=1965, total_copies=1, available_copies=1)
        self.client.login(username='sr', password='StrongPass123')

    def test_invalid_year_shows_message_not_error_page(self):
        for name in ('books:list', 'books:search'):
            r = self.client.get(reverse(name), {'year': 'abc'})
            self.assertEqual(r.status_code, 200)
            self.assertContains(r, 'Publication year must be a number')
            self.assertEqual(len(r.context['page_obj'].object_list), 0)

    def test_extreme_inputs_return_200(self):
        for params in ({'year': '99999999999999999999'}, {'year': '-5'}, {'q': '\x00x'}, {'q': 'x' * 5000},
                       {'category': '%'}, {'page': '999999'}, {'page': '-1'}, {'availability': 'bogus'}):
            for name in ('books:list', 'books:search'):
                self.assertEqual(self.client.get(reverse(name), params).status_code, 200, params)

    def test_valid_search_and_empty_results(self):
        r = self.client.get(reverse('books:search'), {'q': 'dune', 'year': '1965'})
        self.assertContains(r, 'Dune')
        r = self.client.get(reverse('books:search'), {'q': 'zzzz-nothing'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.context['page_obj'].object_list), 0)

    def test_database_error_is_handled(self):
        with mock.patch('django.core.paginator.Paginator.get_page', side_effect=DatabaseError('secret')):
            with self.assertLogs('library', level='ERROR'):
                r = self.client.get(reverse('books:search'), {'q': 'x'})
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, 'secret')


class ProductionErrorPageTests(TestCase):
    @override_settings(DEBUG=False)
    def test_404_and_500_pages_are_safe(self):
        c = Client(raise_request_exception=False)
        r = c.get('/definitely/not/a/page/')
        self.assertEqual(r.status_code, 404)
        self.assertContains(r, 'Page not found', status_code=404)
        user = User.objects.create_user(username='ep', email='ep@x.com', password='StrongPass123', role=User.Role.USER, library_card_id='CARD960')
        c.login(username='ep', password='StrongPass123')
        with mock.patch('books.views.safe_page', side_effect=RuntimeError('SECRET-DETAIL')):
            r = c.get(reverse('books:list'))
        self.assertEqual(r.status_code, 500)
        self.assertContains(r, 'Something went wrong', status_code=500)
        self.assertNotContains(r, 'SECRET-DETAIL', status_code=500)
        self.assertNotContains(r, 'Traceback', status_code=500)

    @override_settings(DEBUG=False)
    def test_403_page_for_members_on_staff_pages(self):
        User.objects.create_user(username='m3', email='m3@x.com', password='StrongPass123', role=User.Role.USER, library_card_id='CARD961')
        c = Client(raise_request_exception=False); c.login(username='m3', password='StrongPass123')
        r = c.get(reverse('accounts:user_list'))
        self.assertContains(r, 'Access denied', status_code=403)
