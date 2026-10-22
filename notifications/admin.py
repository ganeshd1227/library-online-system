from django.contrib import admin
from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('recipient', 'category', 'message', 'is_read', 'created_at')
    list_filter = ('category', 'is_read')
    search_fields = ('recipient__username', 'message')
    ordering = ('-created_at',)
