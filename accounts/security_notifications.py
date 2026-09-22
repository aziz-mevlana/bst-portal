import logging

from django.db import transaction
from django.urls import reverse

from core.models import Notification
from core.notifications import create_notification

from .email_service import send_transactional_email


logger = logging.getLogger(__name__)

PASSWORD_CHANGED_TITLE = 'Parolanız değiştirildi'
PASSWORD_CHANGED_MESSAGE = (
    'BST Portal hesabınızın parolası değiştirildi. Bu işlemi siz yapmadıysanız '
    'hesabınızı güvene almak için hemen yeniden parola sıfırlayın.'
)


def queue_password_changed_security_notice(user, *, event_key):
    """Notify the account owner after a committed password change."""
    user_id = user.pk
    recipient_email = user.email
    recipient_name = user.first_name or user.username
    dedupe_key = f'password-changed:{event_key}'

    def send_notice():
        try:
            if Notification.objects.filter(
                recipient_id=user_id,
                dedupe_key=dedupe_key,
            ).exists():
                return
            create_notification(
                recipient=user,
                notification_type='system',
                title=PASSWORD_CHANGED_TITLE,
                message=PASSWORD_CHANGED_MESSAGE,
                target_url=reverse('accounts:portfolio_settings'),
                dedupe_key=dedupe_key,
                force=True,
            )
        except Exception:
            logger.exception(
                'Parola değişikliği platform bildirimi oluşturulamadı.',
                extra={'user_id': user_id},
            )

        try:
            send_transactional_email(
                'BST Portal - Parolanız değiştirildi',
                (
                    f'Merhaba {recipient_name},\n\n'
                    'BST Portal hesabınızın parolası başarıyla değiştirildi.\n\n'
                    'Bu işlemi siz yapmadıysanız hesabınızı güvene almak için hemen '
                    'yeniden parola sıfırlayın.\n\n'
                    'BST Portal'
                ),
                recipient_email,
            )
        except Exception:
            logger.exception(
                'Parola değişikliği güvenlik e-postası gönderilemedi.',
                extra={'user_id': user_id},
            )

    transaction.on_commit(send_notice)
