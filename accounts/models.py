"""
Custom user model for the Library Management System, plus the
PasswordResetOTP model that backs the OTP-based "forgot password" flow.

A SINGLE custom User model with a `role` field is used instead of
separate Admin/Librarian/User models. This keeps Django's built-in
authentication (login, password hashing, permissions) working out of
the box, while letting us branch UI/behaviour based on role.

IMPORTANT (role separation): an Admin account has role=ADMIN and a
Librarian account has role=LIBRARIAN — NEITHER of them has role=USER.
Every "list users" query in this project filters `role=User.Role.USER`
specifically, so the Admin/Librarian accounts never show up mixed in
with ordinary member accounts (see accounts/views.py `user_list`).

Passwords are NEVER stored in plain text: AbstractUser already stores
only a salted hash (PBKDF2 by default) via Django's auth machinery.
"""
import secrets
import string

from django.contrib.auth.models import AbstractUser
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone


phone_validator = RegexValidator(
    regex=r'^\+?[0-9]{7,15}$',
    message="Enter a valid phone number (7-15 digits, optional leading +).",
)


class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = 'ADMIN', 'Admin'
        LIBRARIAN = 'LIBRARIAN', 'Librarian'
        USER = 'USER', 'User'

    email = models.EmailField(unique=True, db_index=True)
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.USER, db_index=True)

    phone_number = models.CharField(
        max_length=20, blank=True, null=True, unique=True,
        validators=[phone_validator], db_index=True,
    )
    library_card_id = models.CharField(
        max_length=20, blank=True, null=True, unique=True, db_index=True,
        help_text="Unique library card ID, required for members (Users).",
    )
    employee_id = models.CharField(
        max_length=20, blank=True, null=True, unique=True, db_index=True,
        help_text="Employee/library staff ID, used for Librarians.",
    )

    # Per-user dark/light mode preference, persisted across devices in
    # addition to the client-side localStorage fallback (see theme.js).
    class Theme(models.TextChoices):
        LIGHT = 'LIGHT', 'Light'
        DARK = 'DARK', 'Dark'

    theme_preference = models.CharField(max_length=5, choices=Theme.choices, default=Theme.LIGHT)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    USERNAME_FIELD = 'username'
    REQUIRED_FIELDS = ['email']

    class Meta:
        indexes = [
            models.Index(fields=['email']),
            models.Index(fields=['phone_number']),
            models.Index(fields=['library_card_id']),
        ]

    def __str__(self):
        return f"{self.get_full_name() or self.username} ({self.role})"

    @property
    def is_admin_role(self):
        return self.role == self.Role.ADMIN or self.is_superuser

    @property
    def is_librarian_role(self):
        return self.role == self.Role.LIBRARIAN

    @property
    def is_user_role(self):
        return self.role == self.Role.USER and not self.is_superuser


def generate_otp_code(length=6):
    """Cryptographically secure numeric OTP (uses `secrets`, not `random`)."""
    return ''.join(secrets.choice(string.digits) for _ in range(length))


class PasswordResetOTP(models.Model):
    """
    A single OTP code issued for a password-reset attempt.

    Security properties enforced here (see accounts/views.py for how
    they're used):
      - `code` is only ever compared, never redisplayed in the UI/logs.
      - `expires_at` makes the code time-limited.
      - `is_used` makes the code single-use.
      - `attempts` + settings.OTP_MAX_ATTEMPTS throttles brute-force
        guessing of the 6-digit code.
      - Requesting a new OTP for the same user invalidates older,
        unused OTPs so only the most recent one is ever valid.
    """
    user = models.ForeignKey('accounts.User', on_delete=models.CASCADE, related_name='password_reset_otps')
    code = models.CharField(max_length=8)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)
    attempts = models.PositiveSmallIntegerField(default=0)
    # Set once the code has been verified correctly, so the final
    # "set new password" step can confirm verification happened
    # without re-accepting the raw code in the request body.
    verified_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        indexes = [models.Index(fields=['user', 'is_used'])]
        ordering = ['-created_at']

    def __str__(self):
        return f"OTP for {self.user} (used={self.is_used})"

    @property
    def is_expired(self):
        return timezone.now() >= self.expires_at

    @property
    def is_valid(self):
        return not self.is_used and not self.is_expired

    def mark_verified(self):
        self.verified_at = timezone.now()
        self.save(update_fields=['verified_at'])

    def mark_used(self):
        self.is_used = True
        self.save(update_fields=['is_used'])
