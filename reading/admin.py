from django.contrib import admin
from .models import ReadingSession, Highlight


@admin.register(ReadingSession)
class ReadingSessionAdmin(admin.ModelAdmin):
    list_display = ('user', 'book', 'started_at', 'ended_at', 'duration_seconds', 'last_position')
    list_filter = ('ended_at',)
    search_fields = ('user__username', 'book__title')
    ordering = ('-started_at',)


@admin.register(Highlight)
class HighlightAdmin(admin.ModelAdmin):
    list_display = ('user', 'book', 'selected_text', 'color', 'created_at')
    search_fields = ('user__username', 'book__title', 'selected_text')
    ordering = ('-created_at',)
