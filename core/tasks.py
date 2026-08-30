from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from .models import AnalyticsEvent


@shared_task
def purge_expired_analytics():
    retention_days = max(30, int(getattr(settings, 'ANALYTICS_RETENTION_DAYS', 180)))
    cutoff = timezone.now() - timedelta(days=retention_days)
    deleted, _ = AnalyticsEvent.objects.filter(created_at__lt=cutoff).delete()
    return {'deleted': deleted, 'retention_days': retention_days}
