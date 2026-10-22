from django.contrib import admin
from .models import Book, BookRequest


@admin.register(Book)
class BookAdmin(admin.ModelAdmin):
    list_display = ('title', 'author', 'category', 'publication_year', 'status', 'total_copies', 'available_copies')
    list_filter = ('status', 'category', 'publication_year')
    search_fields = ('title', 'author', 'isbn')
    ordering = ('title',)


@admin.register(BookRequest)
class BookRequestAdmin(admin.ModelAdmin):
    list_display = ('requested_title', 'requested_author', 'user', 'status', 'request_date')
    list_filter = ('status',)
    search_fields = ('requested_title', 'requested_author', 'user__username')
    ordering = ('-request_date',)
