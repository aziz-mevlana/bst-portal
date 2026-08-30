from django.conf import settings
from django.core.mail import send_mail


class EmailConfigurationError(RuntimeError):
    """Raised when transactional email cannot be sent safely."""


def validate_email_configuration():
    smtp_backends = {
        'django.core.mail.backends.smtp.EmailBackend',
        'bst_portal.email_backend.CertifiEmailBackend',
    }
    if settings.EMAIL_BACKEND not in smtp_backends:
        return

    if settings.EMAIL_USE_TLS and settings.EMAIL_USE_SSL:
        raise EmailConfigurationError(
            'EMAIL_USE_TLS ve EMAIL_USE_SSL ayni anda etkin olamaz.'
        )

    required = {
        'EMAIL_HOST': settings.EMAIL_HOST,
        'EMAIL_HOST_USER': settings.EMAIL_HOST_USER,
        'EMAIL_HOST_PASSWORD': settings.EMAIL_HOST_PASSWORD,
        'DEFAULT_FROM_EMAIL': settings.DEFAULT_FROM_EMAIL,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise EmailConfigurationError(
            'Eksik e-posta ayarlari: ' + ', '.join(missing)
        )


def send_transactional_email(subject, message, recipient):
    validate_email_configuration()
    sent_count = send_mail(
        subject=subject,
        message=message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[recipient],
        fail_silently=False,
    )
    if sent_count != 1:
        raise RuntimeError('E-posta sunucusu mesaji kabul etmedi.')
