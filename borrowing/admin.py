from django.contrib import admin
from .models import BorrowRecord


@admin.register(BorrowRecord)
class BorrowRecordAdmin(admin.ModelAdmin):
    list_display = ('user', 'book', 'status', 'borrow_date', 'due_date', 'return_date')
    list_filter = ('status',)
    search_fields = ('user__username', 'book__title')
    ordering = ('-requested_at',)
