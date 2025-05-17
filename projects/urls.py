from django.urls import path
from . import views

app_name = 'projects'

urlpatterns = [
    path('', views.project_list, name='project_list'),
    path('upload/', views.project_upload, name='project_upload'),
    path('<int:project_id>/', views.project_detail, name='project_detail'),
    path('<int:project_id>/update/', views.project_update, name='project_update'),
    path('<int:project_id>/comment/', views.add_comment, name='add_comment'),
] 