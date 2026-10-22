"""
Run this periodically (e.g. via cron every few minutes) to finalize
reading sessions whose heartbeat went silent — for example the
browser crashed, the laptop lost power, or the network dropped before
the normal "end session" beacon could fire.

    python manage.py close_stale_sessions
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from reading.models import ReadingSession
from reading.views import STALE_SESSION_SECONDS, _finalize


class Command(BaseCommand):
    help = "Finalize reading sessions whose heartbeat has gone silent for too long."

    def handle(self, *args, **options):
        cutoff = timezone.now() - timezone.timedelta(seconds=STALE_SESSION_SECONDS)
        stale_sessions = ReadingSession.objects.filter(ended_at__isnull=True, last_heartbeat_at__lt=cutoff)
        count = 0
        for session in stale_sessions:
            _finalize(session, session.last_heartbeat_at)
            count += 1
        self.stdout.write(self.style.SUCCESS(f"Closed {count} stale reading session(s)."))
