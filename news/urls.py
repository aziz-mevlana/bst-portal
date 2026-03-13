from django.urls import path
from . import views

app_name = 'news'

urlpatterns = [
    path('', views.news_list, name='news_list'),
    path('load-more/', views.news_load_more, name='news_load_more'),
    path('<int:pk>/duzenle/', views.edit_news, name='edit_news'),
    path('<int:pk>/sil/', views.delete_news, name='delete_news'),
    path('<int:pk>/', views.news_detail, name='news_detail'),
    path('yeni/', views.create_news, name='create_news'),
]
