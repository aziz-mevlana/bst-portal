from django.urls import path
from . import views

app_name = 'events'

urlpatterns = [
    path('', views.event_list, name='event_list'),
    path('load-more/', views.event_load_more, name='event_load_more'),
    path('<int:event_id>/duzenle/', views.edit_event, name='edit_event'),
    path('<int:event_id>/sil/', views.delete_event, name='delete_event'),
    path('<int:event_id>/', views.event_detail, name='event_detail'),
    path('yeni/', views.create_event, name='create_event'),
]
