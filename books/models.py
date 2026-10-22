"""
Book catalogue models.

Two ways a book's content can be read online (see reading/views.py):
  1. `book_file` is a PDF -> rendered with a PDF.js-based page viewer
     (prev/next page, zoom, fullscreen, progress), streamed through an
     authenticated Django view rather than linked directly from MEDIA,
     so logged-out/unauthorized requests can't just download the file.
  2. `content_text` holds sanitized text/HTML -> rendered in the
     lightweight built-in text reader (used for TXT/EPUB-sourced or
     hand-entered content).
"""
import datetime
import os

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models


def validate_book_file_extension(value):
    ext = os.path.splitext(value.name)[1].lower()
    if ext not in settings.ALLOWED_BOOK_FILE_EXTENSIONS:
        raise ValidationError(f"Unsupported file type '{ext}'. Allowed: {settings.ALLOWED_BOOK_FILE_EXTENSIONS}")


def validate_cover_extension(value):
    ext = os.path.splitext(value.name)[1].lower()
    if ext not in settings.ALLOWED_COVER_IMAGE_EXTENSIONS:
        raise ValidationError(f"Unsupported image type '{ext}'. Allowed: {settings.ALLOWED_COVER_IMAGE_EXTENSIONS}")


def validate_file_size(value):
    limit_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if value.size > limit_bytes:
        raise ValidationError(f"File too large. Max size is {settings.MAX_UPLOAD_SIZE_MB} MB.")


class BookQuerySet(models.QuerySet):
    def for_listing(self):
        """Lightweight rows for cards/lists: skips the (potentially huge) content_text column."""
        return self.defer('content_text').annotate(
            has_text=models.ExpressionWrapper(~models.Q(content_text=''), output_field=models.BooleanField()))


class Book(models.Model):
    class Status(models.TextChoices):
        AVAILABLE = 'AVAILABLE', 'Available'
        BORROWED = 'BORROWED', 'Borrowed'
        UNAVAILABLE = 'UNAVAILABLE', 'Unavailable'
        RESERVED = 'RESERVED', 'Reserved'

    objects = BookQuerySet.as_manager()

    title = models.CharField(max_length=255, db_index=True)
    author = models.CharField(max_length=255, db_index=True)
    isbn = models.CharField(max_length=20, unique=True, blank=True, null=True)
    category = models.CharField(max_length=100, blank=True, db_index=True)
    publication_year = models.PositiveIntegerField(
        validators=[MinValueValidator(1400), MaxValueValidator(datetime.date.today().year)],
        db_index=True,
    )
    description = models.TextField(blank=True)

    cover_image = models.ImageField(
        upload_to='covers/', blank=True, null=True,
        validators=[validate_cover_extension, validate_file_size],
    )
    book_file = models.FileField(
        upload_to='books/', blank=True, null=True,
        validators=[validate_book_file_extension, validate_file_size],
        help_text="Optional source file (PDF/EPUB/TXT). PDFs are rendered in the online page-by-page reader.",
    )
    content_text = models.TextField(blank=True, help_text="Sanitized text/HTML shown in the lightweight text reader (used when there's no PDF).")

    total_copies = models.PositiveIntegerField(default=1)
    available_copies = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.AVAILABLE, db_index=True)

    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='books_added',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['title']
        indexes = [
            models.Index(fields=['title']),
            models.Index(fields=['author']),
            models.Index(fields=['publication_year']),
        ]

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.cover_image and kwargs.get('update_fields') is None:
            _optimize_cover(self)

    def __str__(self):
        return f"{self.title} by {self.author}"

    def clean(self):
        if self.available_copies > self.total_copies:
            raise ValidationError("Available copies cannot exceed total copies.")

    def refresh_status(self):
        if self.available_copies <= 0:
            self.status = self.Status.BORROWED
        else:
            self.status = self.Status.AVAILABLE
        self.save(update_fields=['status'])

    @property
    def borrowed_copies(self):
        return self.total_copies - self.available_copies

    @property
    def is_pdf(self):
        return bool(self.book_file and self.book_file.name.lower().endswith('.pdf'))

    @property
    def has_readable_content(self):
        if self.is_pdf:
            return True
        if 'content_text' in self.get_deferred_fields():
            return bool(getattr(self, 'has_text', False))  # annotated by Book.objects.for_listing()
        return bool(self.content_text)

    @property
    def cover_thumb_url(self):
        """Small (<=320px) cover generated on upload; falls back to the original via <img onerror>."""
        if not self.cover_image:
            return ''
        head, name = self.cover_image.name.rsplit('/', 1) if '/' in self.cover_image.name else ('covers', self.cover_image.name)
        stem = name.rsplit('.', 1)[0]
        return self.cover_image.storage.url(f'{head}/thumbs/{stem}.jpg')


class BookRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        FULFILLED = 'FULFILLED', 'Fulfilled'
        REJECTED = 'REJECTED', 'Rejected'

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='book_requests')
    requested_title = models.CharField(max_length=255)
    requested_author = models.CharField(max_length=255, blank=True)
    requested_year = models.PositiveIntegerField(blank=True, null=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    request_date = models.DateTimeField(auto_now_add=True)
    resolved_date = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ['-request_date']

    def __str__(self):
        return f"{self.requested_title} requested by {self.user}"


def _optimize_cover(book, force=False):
    """Downscale/compress the cover (max 900px) and write a 320px JPEG thumbnail. Idempotent."""
    import os
    from PIL import Image, ImageOps
    try:
        path = book.cover_image.path
        head, name = os.path.split(path)
        thumb_dir = os.path.join(head, 'thumbs')
        thumb_path = os.path.join(thumb_dir, os.path.splitext(name)[0] + '.jpg')
        if not force and os.path.exists(thumb_path) and os.path.getmtime(thumb_path) >= os.path.getmtime(path):
            return
        with Image.open(path) as im:
            im = ImageOps.exif_transpose(im)
            os.makedirs(thumb_dir, exist_ok=True)
            thumb = im.convert('RGB'); thumb.thumbnail((320, 480))
            thumb.save(thumb_path, 'JPEG', quality=80, optimize=True, progressive=True)
            if max(im.size) > 900 or os.path.getsize(path) > 300 * 1024:
                full = im.copy(); full.thumbnail((900, 1350))
                ext = os.path.splitext(name)[1].lower()
                if ext == '.png' and 'A' in im.getbands():
                    full.save(path, 'PNG', optimize=True)
                elif ext == '.webp':
                    full.save(path, 'WEBP', quality=82)
                else:
                    full.convert('RGB').save(path, 'JPEG', quality=82, optimize=True, progressive=True)
    except Exception:  # never block saving a book because an image is odd
        import logging
        logging.getLogger('library').warning("Cover optimisation failed for book %s", book.pk, exc_info=True)
