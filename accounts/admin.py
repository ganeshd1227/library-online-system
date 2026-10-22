from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User, PasswordResetOTP


@admin.register(User)
class LibraryUserAdmin(UserAdmin):
    list_display = ('username', 'email', 'role', 'phone_number', 'library_card_id', 'employee_id', 'is_active', 'created_at')
    list_filter = ('role', 'is_active')
    search_fields = ('username', 'email', 'phone_number', 'library_card_id', 'employee_id')
    ordering = ('-created_at',)

    fieldsets = UserAdmin.fieldsets + (
        ('Library Role Info', {'fields': ('role', 'phone_number', 'library_card_id', 'employee_id', 'theme_preference')}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('Library Role Info', {'fields': ('role', 'email', 'phone_number', 'library_card_id', 'employee_id')}),
    )


@admin.register(PasswordResetOTP)
class PasswordResetOTPAdmin(admin.ModelAdmin):
    # Deliberately does NOT list `code` in list_display to avoid casually
    # exposing OTP codes while browsing the admin.
    list_display = ('user', 'created_at', 'expires_at', 'is_used', 'attempts')
    list_filter = ('is_used',)
    search_fields = ('user__username', 'user__email')
    readonly_fields = ('code', 'created_at')
    ordering = ('-created_at',)
