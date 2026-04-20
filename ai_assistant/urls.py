from django.urls import path
from . import views

app_name = 'ai_assistant'

urlpatterns = [
    path('chat/', views.chat_page, name='chat'),
    path('chat/send/', views.chat_send, name='chat_send'),
    path('sources/', views.source_list, name='source_list'),
    path('sources/add/', views.source_add, name='source_add'),
    path('sources/update/', views.source_update, name='source_update'),
    path('sources/delete/', views.source_delete, name='source_delete'),
    path('faq/', views.faq_stats, name='faq_stats'),
    path('faq/delete/', views.faq_delete, name='faq_delete'),
    path('faq/clear/', views.faq_clear_all, name='faq_clear_all'),
]
