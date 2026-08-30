from django.urls import path
from . import views

app_name = 'events'

urlpatterns = [
    path('', views.event_list, name='event_list'),
    path('load-more/', views.event_load_more, name='event_load_more'),
    path('<int:event_id>/duzenle/', views.edit_event, name='edit_event'),
    path('<int:event_id>/sil/', views.delete_event, name='delete_event'),
    path('<int:event_id>/', views.event_detail, name='event_detail'),
    path('<int:event_id>/register/', views.event_register, name='event_register'),
    path('<int:event_id>/calendar.ics', views.event_calendar, name='event_calendar'),
    path('<int:event_id>/participants/', views.event_participants, name='event_participants'),
    path('registrations/<int:registration_id>/cancel/', views.event_registration_cancel, name='event_registration_cancel'),
    path('registrations/<int:registration_id>/qr.png', views.event_registration_qr, name='event_registration_qr'),
    path('registrations/<int:registration_id>/feedback/', views.event_feedback, name='event_feedback'),
    path('check-in/<str:token>/', views.event_checkin, name='event_checkin'),
    path('yeni/', views.create_event, name='create_event'),
]
