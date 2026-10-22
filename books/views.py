import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone

from accounts.decorators import staff_required
from accounts.search_utils import safe_page
from notifications.models import Notification
from .forms import BookForm, BookSearchForm, BookRequestForm
from .models import Book, BookRequest

logger = logging.getLogger('library')


def _filter_books(request):
    form = BookSearchForm(request.GET or None)
    books = Book.objects.for_listing().order_by('title')

    if form.is_bound and not form.is_valid():
        # Invalid input (e.g. year="abc"): explain it and show no results instead of crashing.
        for errors in form.errors.values():
            for error in errors:
                messages.warning(request, error)
        return Book.objects.none(), form

    if form.is_valid():
        q = form.cleaned_data.get('q')
        category = form.cleaned_data.get('category')
        year = form.cleaned_data.get('year')
        availability = form.cleaned_data.get('availability')

        if q:
            books = books.filter(Q(title__icontains=q) | Q(author__icontains=q))
        if category:
            books = books.filter(category__icontains=category)
        if year:
            books = books.filter(publication_year=year)
        if availability == 'AVAILABLE':
            books = books.filter(available_copies__gt=0)

    return books, form


def _fulfil_matching_requests(book):
    """Notify users whose pending request matches this newly added book."""
    pending = BookRequest.objects.filter(status=BookRequest.Status.PENDING, requested_title__iexact=book.title)
    if book.author:
        pending = pending.filter(Q(requested_author='') | Q(requested_author__iexact=book.author))
    for req in pending:
        req.status = BookRequest.Status.FULFILLED
        req.resolved_date = timezone.now()
        req.save(update_fields=['status', 'resolved_date'])
        Notification.objects.create(
            recipient=req.user, category=Notification.Category.BOOK_STATUS,
            message=f"Good news! '{book.title}' by {book.author} is now available in the library.",
        )


@login_required
def book_list(request):
    books, form = _filter_books(request)
    page_obj, _ = safe_page(request, books, 12)
    try:
        categories = list(Book.objects.exclude(category='').values_list('category', flat=True).distinct().order_by('category'))
    except Exception:
        logger.exception("Could not load categories")
        categories = []
    return render(request, 'books/book_list.html', {'page_obj': page_obj, 'form': form, 'categories': categories})


@login_required
def book_search(request):
    books, form = _filter_books(request)
    searched = bool(request.GET.get('q') or request.GET.get('category') or request.GET.get('year'))
    page_obj, _ = safe_page(request, books, 12)
    request_form = BookRequestForm(initial={'requested_title': request.GET.get('q', '')})
    context = {'page_obj': page_obj, 'form': form, 'searched': searched, 'request_form': request_form}
    return render(request, 'books/book_search.html', context)


@login_required
def book_detail(request, pk):
    book = get_object_or_404(Book, pk=pk)
    return render(request, 'books/book_detail.html', {'book': book})


@login_required
def request_book(request):
    if request.method == 'POST':
        form = BookRequestForm(request.POST)
        if form.is_valid():
            book_request = form.save(commit=False)
            book_request.user = request.user
            book_request.save()

            from django.contrib.auth import get_user_model
            User = get_user_model()
            staff = User.objects.filter(role__in=[User.Role.LIBRARIAN, User.Role.ADMIN])
            Notification.objects.bulk_create([
                Notification(
                    recipient=staff_member,
                    category=Notification.Category.BOOK_REQUEST,
                    message=f"{request.user.get_full_name() or request.user.username} requested the book '{book_request.requested_title}'.",
                )
                for staff_member in staff
            ])
            messages.success(request, "Your request has been sent to the library staff.")
        else:
            messages.error(request, "Please provide the book title, author name and published year.")
    return redirect('books:search')


# ---------------------------------------------------------------
# BOOK CRUD (Admin + Librarian)
# ---------------------------------------------------------------
@staff_required
def book_create(request):
    form = BookForm(request.POST or None, request.FILES or None)
    if request.method == 'POST' and form.is_valid():
        book = form.save(commit=False)
        book.added_by = request.user
        try:
            book.full_clean()
        except ValidationError as e:
            for field, errs in e.message_dict.items():
                for err in errs:
                    form.add_error(field if field in form.fields else None, err)
            return render(request, 'books/book_form.html', {'form': form, 'title': 'Add Book'})
        book.save()
        _fulfil_matching_requests(book)
        logger.info("%s added book '%s'", request.user.username, book.title)
        messages.success(request, f"Book '{book.title}' added successfully.")
        return redirect('books:list')
    return render(request, 'books/book_form.html', {'form': form, 'title': 'Add Book'})


@staff_required
def book_edit(request, pk):
    book = get_object_or_404(Book, pk=pk)
    form = BookForm(request.POST or None, request.FILES or None, instance=book)
    if request.method == 'POST' and form.is_valid():
        book = form.save(commit=False)
        try:
            book.full_clean()
        except ValidationError as e:
            for field, errs in e.message_dict.items():
                for err in errs:
                    form.add_error(field if field in form.fields else None, err)
            return render(request, 'books/book_form.html', {'form': form, 'title': 'Edit Book'})
        book.save()
        messages.success(request, "Book updated successfully.")
        return redirect('books:list')
    return render(request, 'books/book_form.html', {'form': form, 'title': 'Edit Book'})


@staff_required
def book_delete(request, pk):
    book = get_object_or_404(Book, pk=pk)
    if request.method == 'POST':
        title = book.title
        book.delete()
        messages.success(request, f"Book '{title}' deleted.")
        return redirect('books:list')
    return render(request, 'books/confirm_delete.html', {'book': book})


@staff_required
def book_requests_list(request):
    requests_qs = BookRequest.objects.select_related('user').order_by('-request_date')
    page_obj, _ = safe_page(request, requests_qs, 15)
    return render(request, 'librarian/book_requests.html', {'page_obj': page_obj})


@staff_required
def book_request_resolve(request, pk, action):
    book_request = get_object_or_404(BookRequest, pk=pk)
    if action == 'fulfill':
        book_request.status = BookRequest.Status.FULFILLED
    elif action == 'reject':
        book_request.status = BookRequest.Status.REJECTED
    else:
        messages.error(request, "Invalid action.")
        return redirect('books:requests_list')

    book_request.resolved_date = timezone.now()
    book_request.save(update_fields=['status', 'resolved_date'])

    Notification.objects.create(
        recipient=book_request.user,
        category=Notification.Category.BOOK_REQUEST,
        message=f"Your request for '{book_request.requested_title}' was {book_request.status.lower()}.",
    )
    messages.success(request, "Request updated.")
    return redirect('books:requests_list')
