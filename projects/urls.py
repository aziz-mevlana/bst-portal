from django.urls import path
from . import views

app_name = 'projects'

urlpatterns = [
    path('', views.project_list, name='project_list'),
    path('load-more/', views.project_load_more, name='project_load_more'),
    path('requests/', views.request_list, name='request_list'),
    path('requests/create/', views.request_create, name='request_create'),
    path('requests/<int:request_id>/edit/', views.request_edit, name='request_edit'),
    path('create/', views.project_create, name='project_create'),
    path('<int:project_id>/', views.project_detail, name='project_detail'),
    path('<int:project_id>/update/', views.project_update, name='project_update'),
    path('<int:project_id>/add-update/', views.add_project_update, name='add_project_update'),
    path('<int:project_id>/add-comment/', views.add_comment, name='add_comment'),
    path('comment/<int:comment_id>/edit/', views.edit_comment, name='edit_comment'),
    path('comment/<int:comment_id>/delete/', views.delete_comment, name='delete_comment'),
    # Approval flow URLs
    path('<int:project_id>/approve/', views.approve_project, name='approve_project'),
    path('<int:project_id>/feedback/', views.send_feedback, name='send_feedback'),
    path('<int:project_id>/feedback/get/', views.get_feedback, name='get_feedback'),
    path('<int:project_id>/start/', views.start_project, name='start_project'),
    path('<int:project_id>/complete/', views.complete_project, name='complete_project'),
    path('<int:project_id>/change-status/', views.change_project_status, name='change_project_status'),
]