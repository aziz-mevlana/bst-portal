from django.urls import path
from . import views

app_name = 'dashboard'

urlpatterns = [
    path('', views.dashboard_home, name='home'),
    path('requests/', views.dashboard_requests, name='requests'),
    path('students/', views.dashboard_students, name='students'),
    path('students/load-more/', views.dashboard_students_load_more, name='students_load_more'),
    path('projects/', views.dashboard_projects, name='projects'),
    path('projects/load-more/', views.dashboard_projects_load_more, name='projects_load_more'),
    path('alumni/', views.dashboard_alumni, name='alumni'),
    path('alumni/load-more/', views.dashboard_alumni_load_more, name='alumni_load_more'),
    path('alumni/match/', views.match_alumni, name='match_alumni'),
    path('alumni/unmatch/', views.unmatch_alumni, name='unmatch_alumni'),
    path('academics/', views.dashboard_academics, name='academics'),
    path('academics/approve/', views.approve_academic, name='approve_academic'),
    path('users/search/', views.search_users, name='search_users'),
    path('students/update-class/', views.update_student_class, name='update_student_class'),
    path('skills/', views.dashboard_skills, name='skills'),
    path('skills/delete/', views.delete_skill, name='delete_skill'),
]
