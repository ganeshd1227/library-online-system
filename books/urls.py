from django.urls import path
from . import views

app_name = 'books'

urlpatterns = [
    path('', views.book_list, name='list'),
    path('search/', views.book_search, name='search'),
    path('request/', views.request_book, name='request_book'),
    path('requests/', views.book_requests_list, name='requests_list'),
    path('requests/<int:pk>/<str:action>/', views.book_request_resolve, name='requests_resolve'),
    path('add/', views.book_create, name='create'),
    path('<int:pk>/', views.book_detail, name='detail'),
    path('<int:pk>/edit/', views.book_edit, name='edit'),
    path('<int:pk>/delete/', views.book_delete, name='delete'),
]
