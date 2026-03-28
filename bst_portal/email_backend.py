import ssl
from django.core.mail.backends.smtp import EmailBackend


class CertifiEmailBackend(EmailBackend):
    def open(self):
        if self.connection:
            return False
        try:
            self.connection = self.connection_class(
                self.host, self.port, timeout=self.timeout
            )
            if self.use_tls:
                context = ssl.create_default_context()
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
                self.connection.starttls(context=context)
            if self.username and self.password:
                self.connection.login(self.username, self.password)
            return True
        except Exception:
            if not self.fail_silently:
                raise
