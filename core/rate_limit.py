import hashlib
import hmac

from django.conf import settings
from django.core.cache import cache


def _identity_digest(request):
    if request.user.is_authenticated:
        identity = f'user:{request.user.pk}'
    else:
        identity = f'ip:{request.META.get("REMOTE_ADDR", "unknown")}'
    return hmac.new(
        settings.SECRET_KEY.encode('utf-8'),
        identity.encode('utf-8'),
        hashlib.sha256,
    ).hexdigest()


def is_rate_limited(request, *, scope, limit, window_seconds):
    """Return True after a privacy-safe identity exceeds the fixed-window limit."""

    key = f'rate-limit:{scope}:{_identity_digest(request)}'
    if cache.add(key, 1, timeout=window_seconds):
        return False
    try:
        count = cache.incr(key)
    except ValueError:
        cache.set(key, 1, timeout=window_seconds)
        count = 1
    return count > limit
