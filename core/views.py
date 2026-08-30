from django.core.cache import cache
from django.contrib.auth.decorators import login_required
from django.db import connection
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from .models import Notification


@require_GET
@never_cache
def health_check(request):
    checks = {'database': False, 'cache': False}
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            checks['database'] = cursor.fetchone()[0] == 1
    except Exception:
        pass

    try:
        cache.set('health-check', 'ok', 10)
        checks['cache'] = cache.get('health-check') == 'ok'
    except Exception:
        pass

    healthy = all(checks.values())
    return JsonResponse(
        {'status': 'ok' if healthy else 'degraded', 'checks': checks},
        status=200 if healthy else 503,
    )


@require_GET
def robots_txt(request):
    sitemap_url = request.build_absolute_uri('/sitemap.xml')
    content = (
        'User-agent: *\n'
        'Disallow: /admin/\n'
        'Disallow: /dashboard/\n'
        'Disallow: /accounts/\n'
        f'Sitemap: {sitemap_url}\n'
    )
    return HttpResponse(content, content_type='text/plain; charset=utf-8')


@login_required
def notification_list(request):
    notifications = request.user.notifications.select_related('actor')[:100]
    return render(request, 'core/notification_list.html', {'notifications': notifications})


@login_required
@require_POST
def notification_mark_read(request, notification_id):
    notification = get_object_or_404(Notification, pk=notification_id, recipient=request.user)
    if notification.read_at is None:
        notification.read_at = timezone.now()
        notification.save(update_fields=['read_at'])
    target = notification.target_url if notification.target_url.startswith('/') and not notification.target_url.startswith('//') else ''
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': True, 'target_url': target or '/notifications/'})
    return redirect(target or 'core:notification_list')


@login_required
@require_POST
def notification_mark_all_read(request):
    updated = request.user.notifications.filter(read_at__isnull=True).update(read_at=timezone.now())
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': True, 'updated': updated, 'unread_count': 0})
    return redirect('core:notification_list')
