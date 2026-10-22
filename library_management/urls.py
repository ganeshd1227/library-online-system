"""
Root URL configuration. Each app owns its own urls.py; we simply
include them here under sensible prefixes.
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('django-admin/', admin.site.urls),  # Django's built-in admin (superuser only)

    path('', include('accounts.urls')),             # login, logout, OTP password reset, dashboards
    path('books/', include('books.urls')),           # book CRUD, search, requests
    path('borrowing/', include('borrowing.urls')),    # borrow records
    path('reading/', include('reading.urls')),        # reader, timer, highlights
    path('notifications/', include('notifications.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATICFILES_DIRS[0])
