import hashlib
import hmac
import ipaddress

from django.conf import settings
from django.core.cache import cache


def _client_ip(request):
    remote = request.META.get('REMOTE_ADDR', 'unknown')
    try:
        remote_address = ipaddress.ip_address(remote)
    except ValueError:
        return 'unknown'

    trusted = set(getattr(settings, 'TRUSTED_PROXY_IPS', ()))
    if str(remote_address) in trusted:
        forwarded = request.META.get('HTTP_X_REAL_IP', '').strip()
        try:
            return str(ipaddress.ip_address(forwarded))
        except ValueError:
            pass
    return str(remote_address)


def _identity_digest(request, identifier=None):
    if identifier is not None:
        identity = f'identifier:{str(identifier).strip().casefold()}'
    elif request.user.is_authenticated:
        identity = f'user:{request.user.pk}'
    else:
        identity = f'ip:{_client_ip(request)}'
    return hmac.new(
        settings.SECRET_KEY.encode('utf-8'),
        identity.encode('utf-8'),
        hashlib.sha256,
    ).hexdigest()


def is_rate_limited(request, *, scope, limit, window_seconds, identifier=None):
    """Return True after a privacy-safe identity exceeds the fixed-window limit."""

    key = f'rate-limit:{scope}:{_identity_digest(request, identifier=identifier)}'
    if cache.add(key, 1, timeout=window_seconds):
        return False
    try:
        count = cache.incr(key)
    except ValueError:
        cache.set(key, 1, timeout=window_seconds)
        count = 1
    return count > limit
