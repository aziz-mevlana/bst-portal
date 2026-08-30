from .models import Notification


def create_notification(*, recipient, notification_type, message, target_url='', actor=None, title='', dedupe_key='', force=False):
    """Create an in-app notification while suppressing self-notifications."""
    if not recipient or (actor and recipient.pk == actor.pk):
        return None
    preferences = getattr(recipient, 'communication_preferences', None)
    if not force and preferences is not None and not preferences.platform_notifications:
        return None
    values = {
        'recipient': recipient,
        'actor': actor,
        'notification_type': notification_type,
        'title': title[:120],
        'message': message[:300],
        'target_url': target_url,
        'dedupe_key': dedupe_key[:160],
    }
    if dedupe_key:
        notification, _ = Notification.objects.get_or_create(
            recipient=recipient, dedupe_key=dedupe_key[:160], defaults=values
        )
        return notification
    return Notification.objects.create(**values)
