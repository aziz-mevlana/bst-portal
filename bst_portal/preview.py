"""Preview-only media serving and search-engine exclusion."""
from pathlib import Path

from django.conf import settings
from django.core.exceptions import DisallowedHost
from django.http import FileResponse, Http404, HttpResponse
from django.urls import re_path
from django.views.decorators.http import require_safe

from .urls import handler400, handler403, handler404, handler500
from .urls import urlpatterns as application_urls


class PreviewHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Keep invalid hosts out of custom error templates that build URLs.
        try:
            request.get_host()
        except DisallowedHost:
            return HttpResponse('Bad Request', status=400, content_type='text/plain')
        if request.path == '/robots.txt':
            response = HttpResponse('User-agent: *\nDisallow: /\n', content_type='text/plain')
        else:
            response = self.get_response(request)
        response['X-Robots-Tag'] = 'noindex, nofollow, noarchive'
        return response


@require_safe
def preview_media(request, path):
    root = Path(settings.MEDIA_ROOT).resolve()
    candidate = (root / path).resolve()
    if not candidate.is_relative_to(root) or not candidate.is_file():
        raise Http404
    # Never execute uploaded HTML/SVG in the application's origin.
    inline = candidate.suffix.lower() in {
        '.jpg', '.jpeg', '.png', '.webp', '.gif', '.ico', '.mp4', '.webm', '.pdf',
    }
    response = FileResponse(candidate.open('rb'), as_attachment=not inline)
    response['Content-Security-Policy'] = "sandbox; default-src 'none'"
    response['X-Content-Type-Options'] = 'nosniff'
    return response


urlpatterns = [
    *application_urls,
    re_path(r'^media/(?P<path>.*)$', preview_media),
]
