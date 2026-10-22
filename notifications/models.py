from django.conf import settings
from django.db import models


class Notification(models.Model):
    class Category(models.TextChoices):
        BOOK_REQUEST = 'BOOK_REQUEST', 'Book Request'
        BOOK_STATUS = 'BOOK_STATUS', 'Book Status'
        BORROW_REQUEST = 'BORROW_REQUEST', 'Borrow Request'
        BORROW_STATUS = 'BORROW_STATUS', 'Borrow Status'
        ACCOUNT_ACTIVITY = 'ACCOUNT_ACTIVITY', 'Account Activity'
        GENERAL = 'GENERAL', 'General'

    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notifications')
    category = models.CharField(max_length=20, choices=Category.choices, default=Category.GENERAL)
    message = models.CharField(max_length=500)
    is_read = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['recipient', 'is_read'])]

    def __str__(self):
        return f"To {self.recipient}: {self.message[:40]}"
