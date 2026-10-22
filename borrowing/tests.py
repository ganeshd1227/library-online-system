from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.urls import reverse

from books.models import Book
from .models import BorrowRecord

User = get_user_model()


class BorrowFlowTests(TestCase):
    def setUp(self):
        self.member = User.objects.create_user(username='m', email='m@x.com', password='StrongPass123', role=User.Role.USER, library_card_id='C1')
        self.lib = User.objects.create_user(username='l', email='l@x.com', password='StrongPass123', role=User.Role.LIBRARIAN, employee_id='E1')
        self.book = Book.objects.create(title='B', author='A', publication_year=2000, total_copies=1, available_copies=1)

    def _login(self, u):
        c = Client(); c.login(username=u, password='StrongPass123'); return c

    def test_borrow_approve_return_updates_status_and_counts(self):
        self._login('m').post(reverse('borrowing:request', args=[self.book.pk]))
        rec = BorrowRecord.objects.get()
        lib = self._login('l')
        lib.post(reverse('borrowing:approve', args=[rec.pk]))
        self.book.refresh_from_db()
        self.assertEqual((self.book.available_copies, self.book.status), (0, Book.Status.BORROWED))
        lib.post(reverse('borrowing:return', args=[rec.pk]))
        self.book.refresh_from_db()
        self.assertEqual((self.book.available_copies, self.book.status), (1, Book.Status.AVAILABLE))

    def test_unavailable_book_cannot_be_requested(self):
        Book.objects.filter(pk=self.book.pk).update(available_copies=0)
        self._login('m').post(reverse('borrowing:request', args=[self.book.pk]))
        self.assertEqual(BorrowRecord.objects.count(), 0)

    def test_cannot_reject_approved_loan_and_member_cannot_approve(self):
        self._login('m').post(reverse('borrowing:request', args=[self.book.pk]))
        rec = BorrowRecord.objects.get()
        self.assertEqual(self._login('m').post(reverse('borrowing:approve', args=[rec.pk])).status_code, 403)
        lib = self._login('l')
        lib.post(reverse('borrowing:approve', args=[rec.pk]))
        lib.post(reverse('borrowing:reject', args=[rec.pk]))
        rec.refresh_from_db()
        self.assertEqual(rec.status, BorrowRecord.Status.APPROVED)
