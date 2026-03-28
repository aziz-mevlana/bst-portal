from django.urls import path
from . import views

app_name = 'dashboard'

urlpatterns = [
    path('', views.dashboard_home, name='home'),
    path('requests/', views.dashboard_requests, name='requests'),
    path('students/', views.dashboard_students, name='students'),
    path('projects/', views.dashboard_projects, name='projects'),
]
