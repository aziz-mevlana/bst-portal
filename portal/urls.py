from django.urls import path
from django.views.generic import TemplateView
from .views import IndexView, academic_list, portfolio_detail, talent_list
from .search import global_search

app_name = 'portal'
 
urlpatterns = [
    path('', IndexView.as_view(), name='index'),
    path('search/', global_search, name='global_search'),
    path('talent/', talent_list, name='talent_list'),
    path('academics/', academic_list, name='academic_list'),
    path('u/<slug:slug>/', portfolio_detail, name='portfolio_detail'),
    path('legal/privacy/', TemplateView.as_view(template_name='legal/privacy.html'), name='privacy'),
    path('legal/kvkk/', TemplateView.as_view(template_name='legal/kvkk.html'), name='kvkk_notice'),
    path('legal/terms/', TemplateView.as_view(template_name='legal/terms.html'), name='terms'),
] 
