import hashlib
import hmac

from django.conf import settings
from django.utils import timezone

from .models import AnalyticsEvent


ALLOWED_METADATA_KEYS = {'result_count', 'query_length', 'source_count', 'cached', 'status'}


def _visitor_hash(request):
    if request.user.is_authenticated:
        identity = f'user:{request.user.pk}'
    else:
        identity = f'session:{request.session.session_key or "anonymous"}:{request.META.get("REMOTE_ADDR", "")}'
    return hmac.new(settings.SECRET_KEY.encode(), identity.encode(), hashlib.sha256).hexdigest()


def record_analytics_event(request, *, event_type, target=None, succeeded=None, metadata=None):
    safe_metadata = {
        key: value for key, value in (metadata or {}).items()
        if key in ALLOWED_METADATA_KEYS and isinstance(value, (str, int, float, bool, type(None)))
    }
    event, _ = AnalyticsEvent.objects.get_or_create(
        event_type=event_type,
        target_type=target._meta.label_lower if target else '',
        target_id=str(target.pk) if target else '',
        visitor_hash=_visitor_hash(request),
        date_bucket=timezone.localdate(),
        defaults={
            'succeeded': succeeded,
            'metadata': safe_metadata,
        },
    )
    return event
