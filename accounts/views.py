"""
Views for:
 - Login / logout
 - Role-based dashboard redirect + dashboards (Admin/Librarian/User)
 - Librarian management (Admin only) & User management (Admin + Librarian)
 - Self-service password change (notifies librarians)
 - OTP-based "forgot password" flow (replaces the old reset-link flow)
 - Theme (dark/light) preference toggle
"""
import hmac
import json
import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, get_user_model, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST

from .decorators import admin_required, staff_required
from .search_utils import clean_query, safe_page
from .forms import (
    LoginForm, LibrarianForm, LibraryUserForm, UserSelfPasswordChangeForm,
    ForgotPasswordForm, VerifyOTPForm, SetNewPasswordForm,
)
from .models import PasswordResetOTP, generate_otp_code
from books.models import Book
from borrowing.models import BorrowRecord
from reading.models import ReadingSession
from notifications.models import Notification

logger = logging.getLogger('library')
User = get_user_model()

SESSION_RESET_EMAIL = 'otp_reset_email'
SESSION_RESET_USER_ID = 'otp_reset_user_id'
SESSION_RESET_VERIFIED = 'otp_reset_verified'


# ---------------------------------------------------------------
# AUTHENTICATION
# ---------------------------------------------------------------
def login_view(request):
    if request.user.is_authenticated:
        return redirect('accounts:post_login_redirect')

    form = LoginForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        identifier = form.cleaned_data['identifier'].strip()
        password = form.cleaned_data['password']

        user = authenticate(request, username=identifier, password=password)
        if user is None:
            logger.warning("Failed login attempt for identifier=%s", identifier)
            messages.error(request, "Invalid credentials. Please check and try again.")
        elif not user.is_active:
            messages.error(request, "This account has been deactivated. Contact the library.")
        else:
            login(request, user)
            logger.info("User %s (%s) logged in.", user.username, user.role)
            return _role_redirect(user)  # straight to the dashboard (saves two redirect round-trips)

    return render(request, 'accounts/login.html', {'form': form})


@login_required
def logout_view(request):
    logger.info("User %s logged out.", request.user.username)
    logout(request)
    messages.success(request, "You have been logged out successfully.")
    return redirect('accounts:login')


def _role_redirect(user):
    if user.is_admin_role:
        return redirect('accounts:admin_dashboard')
    if user.is_librarian_role:
        return redirect('accounts:librarian_dashboard')
    return redirect('accounts:user_dashboard')


@login_required
def post_login_redirect(request):
    return _role_redirect(request.user)


# ---------------------------------------------------------------
# DASHBOARDS
# ---------------------------------------------------------------
@admin_required
def admin_dashboard(request):
    # NOTE (role separation): these counts, and every "Users"/"Librarians"
    # listing in this project, filter strictly by `role=`. An Admin account
    # never has role=USER or role=LIBRARIAN, so it can never appear mixed
    # into the normal-user or librarian lists below.
    stats = {
        'total_librarians': User.objects.filter(role=User.Role.LIBRARIAN).count(),
        'total_users': User.objects.filter(role=User.Role.USER).count(),
        'active_users': User.objects.filter(role=User.Role.USER, is_active=True).count(),
        **Book.objects.aggregate(total_books=Count('id'), available_books=Count('id', filter=Q(available_copies__gt=0))),
        'borrowed_books': BorrowRecord.objects.filter(status=BorrowRecord.Status.APPROVED).count(),
        'currently_reading': ReadingSession.objects.filter(ended_at__isnull=True).values('user').distinct().count(),
        'total_reading_sessions': ReadingSession.objects.count(),
    }
    recent_notifications = Notification.objects.filter(recipient=request.user).order_by('-created_at')[:5]
    return render(request, 'admin_panel/dashboard.html', {'stats': stats, 'notifications': recent_notifications})


@staff_required
def librarian_dashboard(request):
    stats = {
        **Book.objects.aggregate(total_books=Count('id'), available_books=Count('id', filter=Q(available_copies__gt=0))),
        'borrowed_books': BorrowRecord.objects.filter(status=BorrowRecord.Status.APPROVED).count(),
        'total_users': User.objects.filter(role=User.Role.USER).count(),
        'active_users': User.objects.filter(role=User.Role.USER, is_active=True).count(),
        'currently_reading': ReadingSession.objects.filter(ended_at__isnull=True).values('user').distinct().count(),
        'active_sessions': ReadingSession.objects.filter(ended_at__isnull=True).count(),
    }
    recent_notifications = Notification.objects.filter(recipient=request.user).order_by('-created_at')[:8]
    return render(request, 'librarian/dashboard.html', {'stats': stats, 'notifications': recent_notifications})


@login_required
def user_dashboard(request):
    if not request.user.is_user_role:
        return redirect('accounts:post_login_redirect')

    user = request.user
    available_books = Book.objects.for_listing().filter(available_copies__gt=0).order_by('title')[:8]
    borrowed = BorrowRecord.objects.filter(user=user, status=BorrowRecord.Status.APPROVED).select_related('book')
    current_session = ReadingSession.objects.filter(user=user, ended_at__isnull=True).select_related('book').first()
    seen, history = set(), []
    for sess in ReadingSession.objects.filter(user=user).select_related('book').order_by('-started_at')[:50]:
        if sess.book_id not in seen:
            seen.add(sess.book_id)
            history.append(sess)
        if len(history) == 6:
            break
    notifications = Notification.objects.filter(recipient=user).order_by('-created_at')[:8]
    total_seconds = ReadingSession.objects.filter(user=user, duration_seconds__isnull=False).aggregate(total=Sum('duration_seconds'))['total'] or 0

    context = {
        'available_books': available_books, 'borrowed': borrowed, 'current_session': current_session,
        'total_seconds': total_seconds, 'history': history, 'notifications': notifications,
    }
    return render(request, 'users/dashboard.html', context)


# ---------------------------------------------------------------
# LIBRARIAN MANAGEMENT (Admin only)
# ---------------------------------------------------------------
@admin_required
def librarian_list(request):
    query = clean_query(request)
    librarians = User.objects.filter(role=User.Role.LIBRARIAN)
    if query:
        librarians = librarians.filter(
            Q(first_name__icontains=query) | Q(last_name__icontains=query) |
            Q(email__icontains=query) | Q(employee_id__icontains=query)
        )
    librarians = librarians.order_by('-created_at')
    page_obj, _ = safe_page(request, librarians, 10)
    return render(request, 'admin_panel/librarian_list.html', {'page_obj': page_obj, 'query': query})


@admin_required
def librarian_create(request):
    form = LibrarianForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        librarian = form.save()
        logger.info("Admin %s created librarian %s", request.user.username, librarian.username)
        messages.success(request, f"Librarian '{librarian.get_full_name()}' created successfully.")
        return redirect('accounts:librarian_list')
    return render(request, 'admin_panel/librarian_form.html', {'form': form, 'title': 'Add Librarian'})


@admin_required
def librarian_edit(request, pk):
    librarian = get_object_or_404(User, pk=pk, role=User.Role.LIBRARIAN)
    form = LibrarianForm(request.POST or None, instance=librarian)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, "Librarian updated successfully.")
        return redirect('accounts:librarian_list')
    return render(request, 'admin_panel/librarian_form.html', {'form': form, 'title': 'Edit Librarian'})


@admin_required
def librarian_delete(request, pk):
    librarian = get_object_or_404(User, pk=pk, role=User.Role.LIBRARIAN)
    if request.method == 'POST':
        name = librarian.get_full_name()
        librarian.delete()
        messages.success(request, f"Librarian '{name}' deleted.")
        return redirect('accounts:librarian_list')
    return render(request, 'admin_panel/confirm_delete.html', {'object': librarian, 'type': 'Librarian'})


@admin_required
@require_POST
def librarian_toggle_status(request, pk):
    librarian = get_object_or_404(User, pk=pk, role=User.Role.LIBRARIAN)
    librarian.is_active = not librarian.is_active
    librarian.save(update_fields=['is_active'])
    messages.success(request, f"Librarian is now {'active' if librarian.is_active else 'inactive'}.")
    return redirect('accounts:librarian_list')


# ---------------------------------------------------------------
# USER (member) MANAGEMENT — Admin + Librarian
# ---------------------------------------------------------------
@staff_required
def user_list(request):
    query = clean_query(request)
    # role=USER only — Admin and Librarian accounts never appear here.
    users = User.objects.filter(role=User.Role.USER)
    if query:
        users = users.filter(
            Q(first_name__icontains=query) | Q(last_name__icontains=query) |
            Q(email__icontains=query) | Q(library_card_id__icontains=query) |
            Q(phone_number__icontains=query)
        )
    users = users.order_by('-created_at')
    page_obj, _ = safe_page(request, users, 10)
    return render(request, 'librarian/user_list.html', {'page_obj': page_obj, 'query': query})


@staff_required
def user_create(request):
    form = LibraryUserForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        member = form.save()
        logger.info("%s created user %s", request.user.username, member.username)
        messages.success(request, f"User '{member.get_full_name()}' created successfully.")
        return redirect('accounts:user_list')
    return render(request, 'librarian/user_form.html', {'form': form, 'title': 'Add User'})


@staff_required
def user_edit(request, pk):
    member = get_object_or_404(User, pk=pk, role=User.Role.USER)
    form = LibraryUserForm(request.POST or None, instance=member)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, "User updated successfully.")
        return redirect('accounts:user_list')
    return render(request, 'librarian/user_form.html', {'form': form, 'title': 'Edit User'})


@staff_required
def user_delete(request, pk):
    member = get_object_or_404(User, pk=pk, role=User.Role.USER)
    if request.method == 'POST':
        name = member.get_full_name()
        member.delete()
        messages.success(request, f"User '{name}' deleted.")
        return redirect('accounts:user_list')
    return render(request, 'admin_panel/confirm_delete.html', {'object': member, 'type': 'User'})


@staff_required
@require_POST
def user_toggle_status(request, pk):
    member = get_object_or_404(User, pk=pk, role=User.Role.USER)
    member.is_active = not member.is_active
    member.save(update_fields=['is_active'])
    messages.success(request, f"User is now {'active' if member.is_active else 'inactive'}.")
    return redirect('accounts:user_list')


@staff_required
def user_reset_password(request, pk):
    member = get_object_or_404(User, pk=pk, role=User.Role.USER)
    if request.method == 'POST':
        new_password = request.POST.get('new_password', '')
        if len(new_password) < 8:
            messages.error(request, "Password must be at least 8 characters long.")
        else:
            member.set_password(new_password)
            member.save(update_fields=['password'])
            messages.success(request, f"Password reset for {member.get_full_name()}.")
            return redirect('accounts:user_list')
    return render(request, 'librarian/reset_password.html', {'member': member})


@staff_required
def user_detail(request, pk):
    member = get_object_or_404(User, pk=pk, role=User.Role.USER)
    sessions = ReadingSession.objects.filter(user=member).select_related('book').order_by('-started_at')
    total_seconds = sessions.aggregate(total=Sum('duration_seconds'))['total'] or 0
    borrowed = BorrowRecord.objects.filter(user=member).select_related('book').order_by('-borrow_date')
    context = {'member': member, 'sessions': sessions[:20], 'total_seconds': total_seconds, 'borrowed': borrowed}
    return render(request, 'librarian/user_detail.html', context)


# ---------------------------------------------------------------
# SELF-SERVICE PASSWORD CHANGE (Users can ONLY change their password)
# ---------------------------------------------------------------
@login_required
def change_password(request):
    form = UserSelfPasswordChangeForm(request.POST or None, user=request.user)
    if request.method == 'POST' and form.is_valid():
        request.user.set_password(form.cleaned_data['new_password'])
        request.user.save(update_fields=['password'])
        update_session_auth_hash(request, request.user)

        staff = User.objects.filter(role__in=[User.Role.LIBRARIAN, User.Role.ADMIN])
        Notification.objects.bulk_create([
            Notification(
                recipient=staff_member,
                category=Notification.Category.ACCOUNT_ACTIVITY,
                message=f"User {request.user.get_full_name() or request.user.username} changed their account password.",
            )
            for staff_member in staff
        ])
        logger.info("User %s changed their password.", request.user.username)
        messages.success(request, "Your password has been changed successfully.")
        return redirect('accounts:post_login_redirect')
    return render(request, 'accounts/change_password.html', {'form': form})


# ---------------------------------------------------------------
# OTP-BASED "FORGOT PASSWORD" FLOW
# ---------------------------------------------------------------
def _email_is_configured():
    """SMTP needs credentials; fail early with a clear log line instead of an obscure SMTP error."""
    if not settings.EMAIL_BACKEND.endswith('smtp.EmailBackend'):
        return True
    return bool(settings.EMAIL_HOST_USER and settings.EMAIL_HOST_PASSWORD
                and 'your-email' not in settings.EMAIL_HOST_USER)


def _issue_otp(user):
    """Create a fresh OTP and email it. Returns True only if the email was actually sent.

    On failure the new OTP row is removed (so the resend cooldown is not consumed and the user
    can retry immediately) and any earlier still-valid OTP is left untouched.
    """
    code = generate_otp_code(settings.OTP_LENGTH)
    otp = PasswordResetOTP.objects.create(
        user=user, code=code,
        expires_at=timezone.now() + timezone.timedelta(minutes=settings.OTP_EXPIRY_MINUTES),
    )
    try:
        if not _email_is_configured():
            raise RuntimeError("EMAIL_HOST_USER / EMAIL_HOST_PASSWORD are not set in .env")
        send_mail(
            subject="Your Library Management System password reset code",
            message=(
                f"Hello {user.get_full_name() or user.username},\n\n"
                f"Your password reset verification code is: {code}\n\n"
                f"This code expires in {settings.OTP_EXPIRY_MINUTES} minutes and can "
                f"only be used once.\n\n"
                f"If you didn't request this, you can safely ignore this email.\n\n"
                f"— Library Management System"
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=False,
        )
    except Exception:
        # Technical detail goes to the server log only (never the OTP, never to the browser).
        logger.error("Could not email password reset OTP for user_id=%s", user.pk, exc_info=True)
        otp.delete()
        return False

    # Only now invalidate older codes: exactly one OTP (the newest) is ever valid.
    PasswordResetOTP.objects.filter(user=user, is_used=False).exclude(pk=otp.pk).update(is_used=True)
    logger.info("Password reset OTP emailed for user_id=%s", user.pk)  # never log the code itself
    return True


def forgot_password(request):
    """Step 1: user submits their email; an OTP is emailed if it matches an active account."""
    form = ForgotPasswordForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        email = form.cleaned_data['email'].strip()
        user = User.objects.filter(email__iexact=email, is_active=True).first()

        if user:
            wait = _resend_cooldown_remaining(user.pk)
            if wait == 0 and not _issue_otp(user):
                # Delivery failed: stay on this page so the user can retry straight away.
                messages.error(request, "We couldn't send the verification code right now. "
                                        "Please check the address and try again in a moment.")
                return render(request, 'accounts/forgot_password.html', {'form': form})
            request.session[SESSION_RESET_USER_ID] = user.pk
        else:
            # Deliberately give no hint either way — avoids account enumeration.
            request.session[SESSION_RESET_USER_ID] = None

        request.session[SESSION_RESET_EMAIL] = email
        request.session[SESSION_RESET_VERIFIED] = False
        # Same neutral wording for every address (a different message would reveal which are registered).
        messages.info(request, "If that email is registered, a verification code has been sent to it.")
        return redirect('accounts:verify_otp')
    return render(request, 'accounts/forgot_password.html', {'form': form})


def verify_otp(request):
    """Step 2: user enters the OTP they received by email."""
    email = request.session.get(SESSION_RESET_EMAIL)
    if not email:
        messages.error(request, "Please start the password reset process again.")
        return redirect('accounts:forgot_password')

    user_id = request.session.get(SESSION_RESET_USER_ID)
    form = VerifyOTPForm(request.POST or None)
    cooldown_remaining = _resend_cooldown_remaining(user_id)

    if request.method == 'POST' and form.is_valid():
        submitted_code = form.cleaned_data['otp_code'].strip()
        otp = _get_latest_otp(user_id)

        if otp is None:
            messages.error(request, "Invalid verification code. Please try again.")
        elif otp.is_used and otp.verified_at is None:
            # Code was invalidated (e.g. superseded by a resend) without ever being used correctly.
            messages.error(request, "This verification code has expired. Please request a new OTP.")
        elif otp.is_expired:
            messages.error(request, "This verification code has expired. Please request a new OTP.")
        elif otp.attempts >= settings.OTP_MAX_ATTEMPTS:
            otp.mark_used()
            messages.error(request, "Too many incorrect attempts. Please request a new OTP.")
        elif not hmac.compare_digest(otp.code.encode(), submitted_code.encode()):
            otp.attempts += 1
            otp.save(update_fields=['attempts'])
            messages.error(request, "Invalid verification code. Please try again.")
        else:
            otp.mark_verified()
            request.session[SESSION_RESET_VERIFIED] = True
            return redirect('accounts:set_new_password')

    return render(request, 'accounts/verify_otp.html', {
        'form': form, 'email': email, 'cooldown_remaining': cooldown_remaining,
        'otp_expiry_minutes': settings.OTP_EXPIRY_MINUTES,
    })


def _get_latest_otp(user_id):
    if not user_id:
        return None
    return PasswordResetOTP.objects.filter(user_id=user_id).order_by('-created_at').first()


def _resend_cooldown_remaining(user_id):
    otp = _get_latest_otp(user_id)
    if not otp:
        return 0
    elapsed = (timezone.now() - otp.created_at).total_seconds()
    remaining = settings.OTP_RESEND_COOLDOWN_SECONDS - elapsed
    return max(0, int(remaining))


@require_POST
def resend_otp(request):
    email = request.session.get(SESSION_RESET_EMAIL)
    if not email:
        return redirect('accounts:forgot_password')

    user_id = request.session.get(SESSION_RESET_USER_ID)
    cooldown_remaining = _resend_cooldown_remaining(user_id)
    if cooldown_remaining > 0:
        messages.error(request, f"Please wait {cooldown_remaining} seconds before requesting another code.")
        return redirect('accounts:verify_otp')

    user = User.objects.filter(pk=user_id, is_active=True).first() if user_id else None
    if user and not _issue_otp(user):
        messages.error(request, "We couldn't send a new code right now. Please try again in a moment.")
        return redirect('accounts:verify_otp')

    messages.info(request, "If that email is registered, a new verification code has been sent to it.")
    return redirect('accounts:verify_otp')


def set_new_password(request):
    """Step 3: user sets a new password after a successfully verified OTP."""
    email = request.session.get(SESSION_RESET_EMAIL)
    user_id = request.session.get(SESSION_RESET_USER_ID)
    verified = request.session.get(SESSION_RESET_VERIFIED)

    if not email or not user_id or not verified:
        messages.error(request, "Please verify your email with a code first.")
        return redirect('accounts:forgot_password')

    user = get_object_or_404(User, pk=user_id)
    form = SetNewPasswordForm(request.POST or None, user=user)

    if request.method == 'POST' and form.is_valid():
        otp = PasswordResetOTP.objects.filter(user=user, verified_at__isnull=False, is_used=False).order_by('-created_at').first()
        if otp is None or otp.is_expired:
            messages.error(request, "Your verification has expired. Please request a new OTP.")
            return redirect('accounts:forgot_password')

        user.set_password(form.cleaned_data['new_password'])
        user.save(update_fields=['password'])
        otp.mark_used()

        for key in (SESSION_RESET_EMAIL, SESSION_RESET_USER_ID, SESSION_RESET_VERIFIED):
            request.session.pop(key, None)

        logger.info("Password reset completed via OTP for user_id=%s", user.pk)
        messages.success(request, "Password reset successfully. You can now log in.")
        return redirect('accounts:login')

    return render(request, 'accounts/set_new_password.html', {'form': form})


# ---------------------------------------------------------------
# THEME (DARK/LIGHT) PREFERENCE
# ---------------------------------------------------------------
@login_required
@require_POST
def set_theme_preference(request):
    """Persists the dark/light choice to the user's account (localStorage
    handles instant client-side persistence; this keeps it in sync across devices)."""
    try:
        data = json.loads(request.body.decode('utf-8'))
        theme = data.get('theme', '').upper()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'error': 'Invalid payload.'}, status=400)

    if theme not in (User.Theme.LIGHT, User.Theme.DARK):
        return JsonResponse({'error': 'Invalid theme.'}, status=400)

    request.user.theme_preference = theme
    request.user.save(update_fields=['theme_preference'])
    return JsonResponse({'ok': True, 'theme': theme})
