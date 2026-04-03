from django.urls import path
from . import views

app_name = 'alumni'

urlpatterns = [
    path('', views.alumni_list, name='alumni_list'),
    path('load-more/', views.load_more_alumni, name='load_more_alumni'),
    path('profile/', views.alumni_profile, name='alumni_profile'),
    path('profile/edit/', views.alumni_profile_edit, name='alumni_profile_edit'),
    path('<str:username>/', views.alumni_detail, name='alumni_detail'),
    path('detail/<int:alumni_id>/', views.alumni_detail_by_id, name='alumni_detail_by_id'),
]
