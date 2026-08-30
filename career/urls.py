from django.urls import path

from . import views

app_name = 'career'

urlpatterns = [
    path('', views.opportunity_list, name='opportunity_list'),
    path('is-birligi/', views.collaboration_create, name='collaboration_create'),
    path('is-birligi/dogrula/', views.collaboration_verify, name='collaboration_verify'),
    path('is-birligi/yonetim/', views.collaboration_manage, name='collaboration_manage'),
    path('is-birligi/yonetim/<int:request_id>/', views.collaboration_review, name='collaboration_review'),
    path('new/', views.opportunity_create, name='opportunity_create'),
    path('opportunities/<slug:slug>/', views.opportunity_detail, name='opportunity_detail'),
    path('opportunities/<int:opportunity_id>/edit/', views.opportunity_edit, name='opportunity_edit'),
    path('opportunities/<int:opportunity_id>/delete/', views.opportunity_delete, name='opportunity_delete'),
    path('opportunities/<int:opportunity_id>/approve/', views.opportunity_approve, name='opportunity_approve'),
    path('mentors/', views.mentor_list, name='mentor_list'),
    path('mentors/profile/', views.mentorship_profile_manage, name='mentorship_profile_manage'),
    path('mentors/<int:mentor_id>/request/', views.mentorship_request_create, name='mentorship_request_create'),
    path('mentorship/', views.mentorship_dashboard, name='mentorship_dashboard'),
    path('mentorship/<int:request_id>/complete/', views.mentorship_request_complete, name='mentorship_request_complete'),
    path('mentorship/<int:request_id>/review/', views.mentorship_review_create, name='mentorship_review_create'),
    path('mentorship/<int:request_id>/<str:decision>/', views.mentorship_request_respond, name='mentorship_request_respond'),
]
