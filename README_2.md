# Library Management System (Django + MySQL)

Roles: **Admin**, **Librarian**, **User**. Vanilla HTML/CSS/JS frontend, Django backend, MySQL database.

## Features
- Role-based access enforced server-side (403 on unauthorized URLs). Admin/Librarian accounts never appear in the normal **Users** list (all lists filter by `role`).
- Login by email / library card ID / phone. No self-registration.
- **OTP password reset** (no reset links): Forgot Password → email OTP → verify → new password. OTPs are generated with `secrets`, expire (default 10 min), are single-use, limited to 5 wrong attempts, resend has a 60s cooldown, and responses never reveal whether an email exists. OTP codes are never logged or shown in the admin list.
- **Online reader**: PDF books render page-by-page with PDF.js (prev/next, page number, zoom, progress bar, fullscreen, resume at last page); books without a PDF use the sanitized text reader with per-user highlights. PDFs are streamed through a login-protected view, not linked directly.
- **Reading timer** persisted server-side (`ReadingSession`: start, heartbeat, end, duration, last position). Refresh resumes the same session. **Stop Reading** saves the session and returns to the Books page.
- Reading notifications (session started / stopped) via the in-app notification system, in-app toasts, and optional browser notifications (permission requested once; toast fallback always shown).
- **Dark mode**: ☀/🌙 toggle, applied before first paint, persisted in localStorage and in the user's account.
- Fullscreen reader (standard + webkit API, graceful error toast).
- Responsive dashboard UI: stat cards, book cards with categories, status pills, toasts, empty/loading states.

## Setup
```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```
MySQL:
```sql
CREATE DATABASE library_management CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```
Edit `.env` (SECRET_KEY, DB_*, EMAIL_*; OTP_* optional), then:
```bash
python manage.py makemigrations accounts books borrowing reading notifications
python manage.py migrate
python manage.py check
python manage.py createsuperuser
python manage.py shell -c "from accounts.models import User; u=User.objects.get(username='YOURNAME'); u.role='ADMIN'; u.save()"
python manage.py runserver
```
Run tests: `python manage.py test`.

## Gmail / OTP email
Use a Gmail **App Password** in `EMAIL_HOST_PASSWORD`. With `DEBUG=True` emails print to the console (so you can read the OTP while developing); with `DEBUG=False` they go via Gmail SMTP.

## Security notes
- CSRF on all forms/fetches, hashed passwords, role checks on every view, highlight/session endpoints scoped to `request.user`.
- Production: do **not** serve `MEDIA_ROOT/books/` publicly (the dev `static()` media route is DEBUG-only and would expose raw PDFs); let only `reading:pdf_stream` read book files. Cache OTP/rate limiting is DB-based; add IP throttling at the proxy if desired.
- Reader copy-protection is UI-level only, not DRM.
- Schedule `python manage.py close_stale_sessions` (cron) to close abandoned sessions.

## Structure
`accounts/` users, roles, OTP · `books/` catalogue · `borrowing/` loans · `reading/` reader, timer, highlights · `notifications/` · `templates/` · `static/{css,js}`


## Show all the superUsers
python manage.py shell -c "from django.contrib.auth import get_user_model; User=get_user_model(); [print(u.id, u.username, u.email) for u in User.objects.filter(is_superuser=True)]"

## Show all users
python manage.py shell -c "from django.contrib.auth import get_user_model; User=get_user_model(); [print(u.id, u.username, u.email, 'Staff:', u.is_staff, 'Superuser:', u.is_superuser) for u in User.objects.all()]"

## Delete a specific superuser by username
python manage.py shell -c "from django.contrib.auth import get_user_model; User=get_user_model(); User.objects.filter(username='admin').delete()"

## Delete a superuser by ID
`For example, ID 3:`
python manage.py shell -c "from django.contrib.auth import get_user_model; User=get_user_model(); User.objects.filter(id=3, is_superuser=True).delete()"

