"""
URL configuration for bst_portal project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.contrib.sitemaps.views import sitemap
from django.urls import path, include, re_path
from django.conf import settings
from django.conf.urls.static import static
import os
from core.sitemaps import ArticleSitemap, OpportunitySitemap, PortfolioSitemap, ProjectSitemap, StaticSitemap
from core.views import health_check, robots_txt
from projects.views import project_uploaded_media

sitemaps = {
    'projects': ProjectSitemap,
    'portfolios': PortfolioSitemap,
    'static': StaticSitemap,
    'opportunities': OpportunitySitemap,
    'news': ArticleSitemap,
}

handler400 = 'core.error_views.bad_request'
handler403 = 'core.error_views.permission_denied'
handler404 = 'core.error_views.page_not_found'
handler500 = 'core.error_views.server_error'

urlpatterns = [
    re_path(
        r'^media/projects/media/(?P<path>.+)$',
        project_uploaded_media,
        name='protected_project_media',
    ),
    path('health/', health_check, name='health_check'),
    path('robots.txt', robots_txt, name='robots_txt'),
    path('sitemap.xml', sitemap, {'sitemaps': sitemaps}, name='django.contrib.sitemaps.views.sitemap'),
    path('', include('portal.urls')),
    path('', include('core.urls')),
    path('admin/', admin.site.urls),
    path('accounts/', include('accounts.urls')),
    path('events/', include('events.urls')),
    path('projects/', include('projects.urls')),
    path('alumni/', include('alumni.urls')),
    path('news/', include('news.urls')),
    path('dashboard/', include('dashboard.urls')),
    path('ai/', include('ai_assistant.urls')),
    path('career/', include('career.urls')),
]

# Serve linkedin profile photos in debug mode
if settings.DEBUG:
    photos_dir = os.path.join(settings.BASE_DIR, 'linkedin_profile_photos')
    urlpatterns += static('/linkedin_profile_photos/', document_root=photos_dir)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
