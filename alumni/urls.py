from django.urls import path
from . import views

app_name = 'alumni'

urlpatterns = [
    path('', views.alumni_list, name='alumni_list'),
    path('profile/', views.alumni_profile, name='alumni_profile'),
    path('profile/edit/', views.alumni_profile_edit, name='alumni_profile_edit'),
    path('tags/', views.tag_list, name='tag_list'),
    path('<str:username>/', views.alumni_detail, name='alumni_detail'),
] 