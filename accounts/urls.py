from django.urls import path
from . import views

app_name = 'accounts'

urlpatterns = [
    # ---- authentication ----
    path('', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('dashboard/', views.post_login_redirect, name='post_login_redirect'),

    # ---- dashboards ----
    path('admin/dashboard/', views.admin_dashboard, name='admin_dashboard'),
    path('librarian/dashboard/', views.librarian_dashboard, name='librarian_dashboard'),
    path('user/dashboard/', views.user_dashboard, name='user_dashboard'),

    # ---- librarian management (Admin only) ----
    path('admin/librarians/', views.librarian_list, name='librarian_list'),
    path('admin/librarians/add/', views.librarian_create, name='librarian_create'),
    path('admin/librarians/<int:pk>/edit/', views.librarian_edit, name='librarian_edit'),
    path('admin/librarians/<int:pk>/delete/', views.librarian_delete, name='librarian_delete'),
    path('admin/librarians/<int:pk>/toggle/', views.librarian_toggle_status, name='librarian_toggle_status'),

    # ---- user (member) management (Admin + Librarian) ----
    path('members/', views.user_list, name='user_list'),
    path('members/add/', views.user_create, name='user_create'),
    path('members/<int:pk>/', views.user_detail, name='user_detail'),
    path('members/<int:pk>/edit/', views.user_edit, name='user_edit'),
    path('members/<int:pk>/delete/', views.user_delete, name='user_delete'),
    path('members/<int:pk>/toggle/', views.user_toggle_status, name='user_toggle_status'),
    path('members/<int:pk>/reset-password/', views.user_reset_password, name='user_reset_password'),

    # ---- self-service password change ----
    path('password/change/', views.change_password, name='change_password'),

    # ---- OTP-based forgot password (replaces the old reset-link flow) ----
    path('password/forgot/', views.forgot_password, name='forgot_password'),
    path('password/forgot/', views.forgot_password, name='password_reset'),  # kept alias for old links
    path('password/verify-otp/', views.verify_otp, name='verify_otp'),
    path('password/resend-otp/', views.resend_otp, name='resend_otp'),
    path('password/new/', views.set_new_password, name='set_new_password'),

    # ---- theme preference ----
    path('theme/set/', views.set_theme_preference, name='set_theme_preference'),
]
