from django.urls import path
from . import views

app_name = 'reading'

urlpatterns = [
    path('read/<int:pk>/', views.reader_view, name='reader'),
    path('read/<int:pk>/file/', views.pdf_file_stream, name='pdf_stream'),

    # timer / session endpoints (JSON, called via fetch/sendBeacon)
    path('session/start/<int:pk>/', views.start_session, name='session_start'),
    path('session/<int:session_id>/heartbeat/', views.heartbeat, name='session_heartbeat'),
    path('session/<int:session_id>/position/', views.update_position, name='session_position'),
    path('session/<int:session_id>/end/', views.end_session, name='session_end'),

    path('stop/<int:pk>/', views.stop_reading, name='stop_reading'),

    # highlight endpoints (JSON)
    path('highlights/<int:pk>/', views.list_highlights, name='highlight_list'),
    path('highlights/<int:pk>/create/', views.create_highlight, name='highlight_create'),
    path('highlights/<int:highlight_id>/delete/', views.delete_highlight, name='highlight_delete'),
]
