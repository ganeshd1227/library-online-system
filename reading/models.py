"""
Reading-timer & highlight models.

READING TIMER DESIGN:
    - `started_at` is set once, when a session begins.
    - `last_heartbeat_at` is refreshed every ~20 seconds by a small JS
      `fetch()` call while the reading page is open and visible. This
      is what lets the server detect "the tab is still open" without
      trusting a client-reported elapsed time.
    - `ended_at` / `duration_seconds` are only written once, when the
      session is finalized (either by the user clicking "Stop Reading",
      or by the `close_stale_sessions` management command cleaning up
      sessions whose heartbeat went silent for too long).
    - `last_position` stores the last page (PDF) or character offset
      (text reader) the user reached, so reopening a book resumes
      roughly where they left off.

MYSQL NOTE: Django's `UniqueConstraint(condition=...)` (a partial/
filtered unique index) is NOT supported on MySQL/MariaDB — only on
PostgreSQL, SQLite and Oracle. Since this project targets MySQL, the
"only one active session per user+book" rule instead uses the classic
unique-with-NULL trick: `active_marker` is 1 while active and reset to
NULL once the session ends. MySQL does not treat NULLs as duplicates
in a unique index, so any number of ended sessions can share
(user, book, NULL), while only one row can ever hold (user, book, 1).
"""
from django.conf import settings
from django.db import models


class ReadingSession(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='reading_sessions')
    book = models.ForeignKey('books.Book', on_delete=models.CASCADE, related_name='reading_sessions')

    started_at = models.DateTimeField(auto_now_add=True)
    last_heartbeat_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(blank=True, null=True)
    duration_seconds = models.PositiveIntegerField(blank=True, null=True)
    last_position = models.PositiveIntegerField(default=0, help_text="Last PDF page or text offset reached.")

    active_marker = models.PositiveSmallIntegerField(default=1, blank=True, null=True)

    class Meta:
        ordering = ['-started_at']
        constraints = [
            models.UniqueConstraint(fields=['user', 'book', 'active_marker'], name='one_active_session_per_user_book')
        ]

    def __str__(self):
        return f"{self.user} reading {self.book} ({'active' if self.ended_at is None else 'ended'})"

    @property
    def is_active(self):
        return self.ended_at is None


class Highlight(models.Model):
    COLOR_CHOICES = [
        ('yellow', 'Yellow'),
        ('green', 'Green'),
        ('blue', 'Blue'),
        ('pink', 'Pink'),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='highlights')
    book = models.ForeignKey('books.Book', on_delete=models.CASCADE, related_name='highlights')

    selected_text = models.TextField()
    start_offset = models.PositiveIntegerField()
    end_offset = models.PositiveIntegerField()
    color = models.CharField(max_length=10, choices=COLOR_CHOICES, default='yellow')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['start_offset']
        indexes = [models.Index(fields=['user', 'book'])]

    def __str__(self):
        return f"Highlight by {self.user} in {self.book}: {self.selected_text[:30]}"
