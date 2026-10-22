"""
Reader page + JSON endpoints for reading-session timing, position
tracking, highlights, and a secure authenticated PDF stream.

SECURITY NOTE: every endpoint here uses `request.user` (the
authenticated session user) for all ownership checks. We NEVER trust a
user_id sent from JavaScript/the request body.

SECURITY NOTE (downloads): the PDF reader never links to the raw
`book_file.url` (which — in DEBUG — is served unauthenticated by
Django's static media handler). Instead the page fetches bytes from
`pdf_file_stream`, a `@login_required` view, so only authenticated
users can retrieve book content at all. In production, additionally
configure your web server/storage so MEDIA_ROOT isn't served directly
and only this view can read uploaded files (see README).
"""
import json
import logging
import re

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, FileResponse, Http404, HttpResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_POST, require_GET

from books.models import Book
from notifications.models import Notification
from .models import ReadingSession, Highlight

logger = logging.getLogger('library')

STALE_SESSION_SECONDS = 90


def _is_tracked(user):
    """Only regular members are timed; admins/librarians read freely."""
    return user.role == 'USER' and not user.is_superuser


def _finalize(session, end_time):
    """Write ended_at/duration_seconds exactly once, and free up `active_marker`
    so a new session for this user+book can start."""
    if session.ended_at is not None:
        return
    session.ended_at = end_time
    delta = (end_time - session.started_at).total_seconds()
    session.duration_seconds = max(0, int(delta))
    session.active_marker = None
    session.save(update_fields=['ended_at', 'duration_seconds', 'active_marker'])


@login_required
def reader_view(request, pk):
    """Render the online reading page — PDF page-viewer or text reader."""
    book = get_object_or_404(Book, pk=pk)

    if not book.has_readable_content:
        return render(request, 'reading/no_content.html', {'book': book})

    highlights = Highlight.objects.filter(user=request.user, book=book).order_by('start_offset')
    highlights_json = json.dumps([
        {'id': h.id, 'text': h.selected_text, 'start': h.start_offset, 'end': h.end_offset, 'color': h.color}
        for h in highlights
    ])

    # Resume position from the user's most recent session (active or ended) for this book.
    last_session = ReadingSession.objects.filter(user=request.user, book=book).order_by('-started_at').first()
    resume_position = last_session.last_position if last_session else 0

    context = {'book': book, 'highlights_json': highlights_json, 'resume_position': resume_position,
               'track_time': _is_tracked(request.user)}
    return render(request, 'reading/reader.html', context)


def _iter_range(fh, start, length, chunk=64 * 1024):
    try:
        fh.seek(start)
        remaining = length
        while remaining > 0:
            data = fh.read(min(chunk, remaining))
            if not data:
                break
            remaining -= len(data)
            yield data
    finally:
        fh.close()


@login_required
def pdf_file_stream(request, pk):
    """Streams the PDF to the authenticated viewer with HTTP Range support, so PDF.js can
    load only the bytes it needs (first page appears without downloading the whole file)."""
    book = get_object_or_404(Book, pk=pk)
    if not book.is_pdf:
        raise Http404("This book has no PDF file.")
    try:
        size = book.book_file.size
        fh = book.book_file.open('rb')
    except (FileNotFoundError, ValueError):
        raise Http404("Book file not found on the server.")

    headers = {'Accept-Ranges': 'bytes', 'Cache-Control': 'private, max-age=3600',
               'Content-Disposition': 'inline; filename="book.pdf"'}
    match = re.match(r'^bytes=(\d*)-(\d*)$', request.headers.get('Range', '').strip())
    if match and (match.group(1) or match.group(2)):
        if match.group(1):
            start = int(match.group(1))
            end = int(match.group(2)) if match.group(2) else size - 1
        else:  # suffix range: last N bytes
            start = max(size - int(match.group(2)), 0)
            end = size - 1
        end = min(end, size - 1)
        if start > end or start >= size:
            fh.close()
            response = HttpResponse(status=416)
            response['Content-Range'] = f'bytes */{size}'
            return response
        response = StreamingHttpResponse(_iter_range(fh, start, end - start + 1), status=206, content_type='application/pdf')
        response['Content-Range'] = f'bytes {start}-{end}/{size}'
        response['Content-Length'] = str(end - start + 1)
    else:
        response = FileResponse(fh, content_type='application/pdf')
        response['Content-Length'] = str(size)
    for key, value in headers.items():
        response[key] = value
    return response


# ---------------------------------------------------------------
# READING SESSION / TIMER ENDPOINTS
# ---------------------------------------------------------------
@login_required
@require_POST
def start_session(request, pk):
    book = get_object_or_404(Book, pk=pk)
    if not _is_tracked(request.user):
        return JsonResponse({'session_id': None, 'tracked': False, 'elapsed_seconds': 0, 'last_position': 0})
    now = timezone.now()

    active = ReadingSession.objects.filter(user=request.user, book=book, ended_at__isnull=True).first()
    if active:
        seconds_since_heartbeat = (now - active.last_heartbeat_at).total_seconds()
        if seconds_since_heartbeat <= STALE_SESSION_SECONDS:
            active.last_heartbeat_at = now
            active.save(update_fields=['last_heartbeat_at'])
            elapsed = int((now - active.started_at).total_seconds())
            return JsonResponse({'session_id': active.id, 'elapsed_seconds': elapsed, 'resumed': True, 'last_position': active.last_position})
        _finalize(active, active.last_heartbeat_at)

    recent = ReadingSession.objects.filter(
        user=request.user, book=book, started_at__gte=now - timezone.timedelta(minutes=10)).exists()
    session = ReadingSession.objects.create(user=request.user, book=book)

    # Skip the notification on quick refreshes/re-opens of the same book.
    if not recent:
        Notification.objects.create(
            recipient=request.user, category=Notification.Category.GENERAL,
            message=f"You started reading '{book.title}'.",
        )
    return JsonResponse({'session_id': session.id, 'elapsed_seconds': 0, 'resumed': False, 'last_position': 0})


@login_required
@require_POST
def heartbeat(request, session_id):
    session = get_object_or_404(ReadingSession, pk=session_id, user=request.user, ended_at__isnull=True)
    session.last_heartbeat_at = timezone.now()
    session.save(update_fields=['last_heartbeat_at'])
    return JsonResponse({'ok': True})


@login_required
@require_POST
def update_position(request, session_id):
    """Saves the current PDF page / text offset so the reader can resume later."""
    session = get_object_or_404(ReadingSession, pk=session_id, user=request.user, ended_at__isnull=True)
    try:
        data = json.loads(request.body.decode('utf-8'))
        position = max(0, int(data.get('position', 0)))
    except (ValueError, json.JSONDecodeError):
        return JsonResponse({'error': 'Invalid position.'}, status=400)
    session.last_position = position
    session.save(update_fields=['last_position'])
    return JsonResponse({'ok': True})


@login_required
@require_POST
def end_session(request, session_id):
    """Called when the user clicks Stop Reading, navigates away (sendBeacon), or closes the reader."""
    try:
        session = ReadingSession.objects.select_related('book').get(pk=session_id, user=request.user, ended_at__isnull=True)
    except ReadingSession.DoesNotExist:
        return JsonResponse({'ok': True, 'already_ended': True})

    now = timezone.now()
    # If the tab went silent (hidden/crashed) don't count the gap as reading time.
    if (now - session.last_heartbeat_at).total_seconds() > STALE_SESSION_SECONDS:
        now = session.last_heartbeat_at
    _finalize(session, now)
    logger.info("Reading session %s ended: %ss", session.id, session.duration_seconds)

    if request.POST.get('auto') == '1':  # page unload/refresh, not an explicit stop
        return JsonResponse({'ok': True, 'duration_seconds': session.duration_seconds})

    # Reading-stopped notification, with the session's total duration.
    minutes, seconds = divmod(session.duration_seconds or 0, 60)
    Notification.objects.create(
        recipient=request.user, category=Notification.Category.GENERAL,
        message=f"You stopped reading '{session.book.title}'. Session time: {minutes}m {seconds}s.",
    )
    return JsonResponse({'ok': True, 'duration_seconds': session.duration_seconds})


# ---------------------------------------------------------------
# HIGHLIGHTS
# ---------------------------------------------------------------
@login_required
@require_POST
def create_highlight(request, pk):
    book = get_object_or_404(Book, pk=pk)
    try:
        data = json.loads(request.body.decode('utf-8'))
        text = data['text'].strip()
        start = int(data['start'])
        end = int(data['end'])
        color = data.get('color', 'yellow')
    except (KeyError, ValueError, json.JSONDecodeError):
        return JsonResponse({'error': 'Invalid highlight payload.'}, status=400)

    if not text or end <= start:
        return JsonResponse({'error': 'Invalid selection range.'}, status=400)
    if color not in dict(Highlight.COLOR_CHOICES):
        color = 'yellow'

    highlight = Highlight.objects.create(
        user=request.user, book=book, selected_text=text[:2000], start_offset=start, end_offset=end, color=color,
    )
    return JsonResponse({'id': highlight.id, 'text': highlight.selected_text, 'start': start, 'end': end, 'color': color})


@login_required
@require_POST
def delete_highlight(request, highlight_id):
    deleted, _ = Highlight.objects.filter(pk=highlight_id, user=request.user).delete()
    if not deleted:
        return JsonResponse({'error': 'Highlight not found.'}, status=404)
    return JsonResponse({'ok': True})


@login_required
@require_GET
def list_highlights(request, pk):
    book = get_object_or_404(Book, pk=pk)
    highlights = Highlight.objects.filter(user=request.user, book=book).order_by('start_offset')
    data = [{'id': h.id, 'text': h.selected_text, 'start': h.start_offset, 'end': h.end_offset, 'color': h.color} for h in highlights]
    return JsonResponse({'highlights': data})


@login_required
@require_POST
def stop_reading(request, pk):
    """Stop the logged-in user's active session for a book (e.g. from the dashboard)."""
    from django.shortcuts import redirect
    session = ReadingSession.objects.filter(user=request.user, book_id=pk, ended_at__isnull=True).select_related('book').first()
    if session:
        _finalize(session, timezone.now())
    return redirect('accounts:post_login_redirect')
