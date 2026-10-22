import datetime

from django.conf import settings
from django.db import models


class BorrowRecord(models.Model):
    class Status(models.TextChoices):
        REQUESTED = 'REQUESTED', 'Requested'
        APPROVED = 'APPROVED', 'Approved'
        REJECTED = 'REJECTED', 'Rejected'
        RETURNED = 'RETURNED', 'Returned'

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='borrow_records')
    book = models.ForeignKey('books.Book', on_delete=models.CASCADE, related_name='borrow_records')
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.REQUESTED, db_index=True)

    borrow_date = models.DateTimeField(blank=True, null=True)
    due_date = models.DateField(blank=True, null=True)
    return_date = models.DateTimeField(blank=True, null=True)
    requested_at = models.DateTimeField(auto_now_add=True)

    handled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='borrow_records_handled',
    )

    class Meta:
        ordering = ['-requested_at']

    def __str__(self):
        return f"{self.user} - {self.book} ({self.status})"

    def default_due_date(self):
        return (self.borrow_date or datetime.datetime.now()).date() + datetime.timedelta(days=14)
