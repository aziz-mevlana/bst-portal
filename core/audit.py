import hashlib
import hmac

from django.conf import settings

from .models import AuditLog


def record_audit_event(*, actor, action, target=None, metadata=None, request=None):
    target_type = ''
    target_id = ''
    if target is not None:
        target_type = target._meta.label_lower
        target_id = str(target.pk)
    client_hash = ''
    if request is not None:
        address = request.META.get('REMOTE_ADDR', 'unknown')
        client_hash = hmac.new(
            settings.SECRET_KEY.encode('utf-8'),
            address.encode('utf-8'),
            hashlib.sha256,
        ).hexdigest()
    return AuditLog.objects.create(
        actor=actor if getattr(actor, 'is_authenticated', False) else None,
        action=action,
        target_type=target_type,
        target_id=target_id,
        metadata=metadata or {},
        client_hash=client_hash,
    )
