from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email
from django.core.exceptions import ValidationError

from accounts.email_service import EmailConfigurationError, send_transactional_email, validate_email_configuration


class Command(BaseCommand):
    help = 'SMTP yapılandırmasını doğrular ve belirtilen adrese test e-postası gönderir.'

    def add_arguments(self, parser):
        parser.add_argument('--to', required=True, dest='recipient', help='Test e-postasının gönderileceği adres')

    def handle(self, *args, **options):
        recipient = options['recipient'].strip()
        try:
            validate_email(recipient)
            validate_email_configuration()
        except (ValidationError, EmailConfigurationError) as exc:
            raise CommandError(str(exc)) from exc
        try:
            send_transactional_email(
                'BST Portal SMTP Testi',
                'Bu iletiyi aldıysanız BST Portal SMTP yapılandırması çalışıyor.',
                recipient,
            )
        except Exception as exc:
            raise CommandError(f'Test e-postası gönderilemedi: {exc}') from exc
        self.stdout.write(self.style.SUCCESS(f'Test e-postası gönderildi: {recipient}'))
