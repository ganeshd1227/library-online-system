from django.core.management.base import BaseCommand

from books.models import Book, _optimize_cover


class Command(BaseCommand):
    help = "Compress existing cover images and generate thumbnails (safe to re-run)."

    def handle(self, *args, **options):
        done = 0
        for book in Book.objects.exclude(cover_image='').exclude(cover_image__isnull=True).defer('content_text'):
            try:
                _optimize_cover(book)
                done += 1
            except FileNotFoundError:
                self.stderr.write(f"Missing cover file for book {book.pk}")
        self.stdout.write(self.style.SUCCESS(f"Processed {done} covers."))
