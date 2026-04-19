from django.urls import path
from . import views

app_name = 'dashboard'

urlpatterns = [
    path('', views.dashboard_home, name='home'),
    path('my-projects/', views.student_my_projects, name='my_projects'),
    path('alumni-projects/', views.alumni_projects, name='alumni_projects'),
    path('news/', views.dashboard_news, name='news'),
    path('news/approve/', views.approve_news, name='news_approve'),
    path('news/reject/', views.reject_news, name='news_reject'),
    path('news/delete/', views.delete_news, name='news_delete'),
    path('news/approve-all/', views.approve_all_news, name='news_approve_all'),
    path('news/keywords/', views.news_keywords, name='news_keywords'),
    path('news/keywords/delete/', views.delete_keyword, name='delete_keyword'),
    path('fetch-news/', views.fetch_news_command, name='fetch_news'),
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
