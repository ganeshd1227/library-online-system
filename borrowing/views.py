"""
Borrowing workflow:

1. A User requests to borrow an available book -> BorrowRecord(status=REQUESTED).
2. A Librarian approves it -> available_copies decreases by 1, status=APPROVED,
   borrow_date/due_date set, Book.status recalculated.
   If the book has no available copies, the user sees
   "This book is currently unavailable." and a notification is created instead.
3. A Librarian marks a book returned -> available_copies increases by 1,
   status=RETURNED, return_date set, Book.status recalculated.

All copy-count changes happen inside a single DB transaction to avoid
race conditions (e.g. two users approved for the last copy at once).
"""
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django.utils import timezone

from accounts.decorators import staff_required
from books.models import Book
from notifications.models import Notification
from .models import BorrowRecord

logger = logging.getLogger('library')


@login_required
@require_POST
def request_borrow(request, book_id):
    book = get_object_or_404(Book, pk=book_id)

    if book.available_copies <= 0:
        Notification.objects.create(
            recipient=request.user, category=Notification.Category.BOOK_STATUS,
            message=f"'{book.title}' is currently unavailable.",
        )
        messages.error(request, "This book is currently unavailable.")
        return redirect('books:detail', pk=book.pk)

    already_requested = BorrowRecord.objects.filter(
        user=request.user, book=book, status__in=[BorrowRecord.Status.REQUESTED, BorrowRecord.Status.APPROVED]
    ).exists()
    if already_requested:
        messages.info(request, "You already have an active request/loan for this book.")
        return redirect('books:detail', pk=book.pk)

    BorrowRecord.objects.create(user=request.user, book=book)

    from django.contrib.auth import get_user_model
    User = get_user_model()
    staff = User.objects.filter(role__in=[User.Role.LIBRARIAN, User.Role.ADMIN])
    Notification.objects.bulk_create([
        Notification(
            recipient=staff_member, category=Notification.Category.BORROW_REQUEST,
            message=f"{request.user.get_full_name() or request.user.username} requested to borrow '{book.title}'.",
        )
        for staff_member in staff
    ])
    messages.success(request, "Your borrow request has been submitted.")
    return redirect('books:detail', pk=book.pk)


@staff_required
def borrow_list(request):
    status_filter = request.GET.get('status', '')
    if status_filter not in dict(BorrowRecord.Status.choices):
        status_filter = ''
    records = BorrowRecord.objects.select_related('user', 'book').all()
    if status_filter:
        records = records.filter(status=status_filter)
    try:
        records = list(records)
    except Exception:
        logger.exception("Could not load borrow records")
        messages.error(request, "We couldn't load the borrow records right now. Please try again in a moment.")
        records = []
    return render(request, 'librarian/borrow_list.html', {
        'records': records, 'status_filter': status_filter, 'statuses': BorrowRecord.Status.choices,
    })


@staff_required
@require_POST
@transaction.atomic
def approve_borrow(request, pk):
    record = get_object_or_404(BorrowRecord.objects.select_for_update(), pk=pk)
    book = record.book

    if record.status != BorrowRecord.Status.REQUESTED:
        messages.error(request, "This request has already been handled.")
        return redirect('borrowing:list')

    if book.available_copies <= 0:
        messages.error(request, "This book is currently unavailable.")
        Notification.objects.create(
            recipient=record.user, category=Notification.Category.BOOK_STATUS,
            message=f"'{book.title}' is currently unavailable.",
        )
        return redirect('borrowing:list')

    book.available_copies -= 1
    book.save(update_fields=['available_copies'])
    book.refresh_status()

    record.status = BorrowRecord.Status.APPROVED
    record.borrow_date = timezone.now()
    record.due_date = record.default_due_date()
    record.handled_by = request.user
    record.save()

    Notification.objects.create(
        recipient=record.user, category=Notification.Category.BORROW_STATUS,
        message=f"Your request to borrow '{book.title}' was approved. Due back {record.due_date}.",
    )
    logger.info("%s approved borrow #%s", request.user.username, record.pk)
    messages.success(request, "Borrow request approved.")
    return redirect('borrowing:list')


@staff_required
@require_POST
def reject_borrow(request, pk):
    record = get_object_or_404(BorrowRecord, pk=pk)
    if record.status != BorrowRecord.Status.REQUESTED:
        messages.error(request, "Only pending requests can be rejected.")
        return redirect('borrowing:list')
    record.status = BorrowRecord.Status.REJECTED
    record.handled_by = request.user
    record.save(update_fields=['status', 'handled_by'])

    Notification.objects.create(
        recipient=record.user, category=Notification.Category.BORROW_STATUS,
        message=f"Your request to borrow '{record.book.title}' was rejected.",
    )
    messages.success(request, "Borrow request rejected.")
    return redirect('borrowing:list')


@staff_required
@require_POST
@transaction.atomic
def mark_returned(request, pk):
    record = get_object_or_404(BorrowRecord.objects.select_for_update(), pk=pk)
    if record.status != BorrowRecord.Status.APPROVED:
        messages.error(request, "Only approved loans can be marked as returned.")
        return redirect('borrowing:list')

    book = record.book
    book.available_copies = min(book.total_copies, book.available_copies + 1)
    book.save(update_fields=['available_copies'])
    book.refresh_status()

    record.status = BorrowRecord.Status.RETURNED
    record.return_date = timezone.now()
    record.save(update_fields=['status', 'return_date'])

    messages.success(request, "Book marked as returned.")
    return redirect('borrowing:list')
