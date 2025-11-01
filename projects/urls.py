from django.urls import path
from . import views

app_name = 'projects'

urlpatterns = [
    path('', views.project_list, name='project_list'),
    path('requests/', views.request_list, name='request_list'),
    path('requests/create/', views.request_create, name='request_create'),
    path('create/', views.project_create, name='project_create'),
    path('<int:project_id>/', views.project_detail, name='project_detail'),
    path('<int:project_id>/update/', views.project_update, name='project_update'),
    path('<int:project_id>/add-update/', views.add_project_update, name='add_project_update'),
    path('<int:project_id>/add-comment/', views.add_comment, name='add_comment'),
] 