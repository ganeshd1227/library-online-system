from django.urls import path
from . import views

app_name = 'borrowing'

urlpatterns = [
    path('', views.borrow_list, name='list'),
    path('request/<int:book_id>/', views.request_borrow, name='request'),
    path('<int:pk>/approve/', views.approve_borrow, name='approve'),
    path('<int:pk>/reject/', views.reject_borrow, name='reject'),
    path('<int:pk>/return/', views.mark_returned, name='return'),
]
