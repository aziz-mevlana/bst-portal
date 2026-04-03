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
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
import os

urlpatterns = [
    path('', include('portal.urls')),
    path('admin/', admin.site.urls),
    path('accounts/', include('accounts.urls')),
    path('events/', include('events.urls')),
    path('projects/', include('projects.urls')),
    path('alumni/', include('alumni.urls')),
    path('news/', include('news.urls')),
    path('dashboard/', include('dashboard.urls')),
]

# Serve linkedin profile photos in debug mode
if settings.DEBUG:
    photos_dir = os.path.join(settings.BASE_DIR, 'linkedin_profile_photos')
    urlpatterns += static('/linkedin_profile_photos/', document_root=photos_dir)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
