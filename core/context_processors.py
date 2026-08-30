NOINDEX_PREFIXES = (
    '/admin/',
    '/accounts/',
    '/dashboard/',
    '/ai/',
    '/projects/requests/',
    '/projects/saved/',
    '/projects/create/',
    '/notifications/',
)


def seo_defaults(request):
    """Supply safe SEO defaults without retaining query strings in canonicals."""
    noindex = any(request.path.startswith(prefix) for prefix in NOINDEX_PREFIXES)
    unread_notifications = 0
    recent_notifications = []
    if request.user.is_authenticated:
        unread_notifications = request.user.notifications.filter(read_at__isnull=True).count()
        recent_notifications = request.user.notifications.select_related('actor')[:10]
    from .models import FooterLink
    footer_groups = {key: [] for key, label in FooterLink.SECTION_CHOICES}
    for link in FooterLink.objects.filter(is_active=True):
        footer_groups[link.section].append(link)
    return {
        'canonical_url': request.build_absolute_uri(request.path),
        'meta_robots': 'noindex,nofollow' if noindex else 'index,follow',
        'unread_notification_count': unread_notifications,
        'recent_notifications': recent_notifications,
        'footer_groups': footer_groups,
    }
