from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from .link_validation import validate_footer_url


class FooterLink(models.Model):
    SECTION_CHOICES = [
        ('navigation', 'Navigasyon'), ('resources', 'Kaynaklar'),
        ('contact', 'İletişim'), ('legal', 'Yasal bağlantılar'),
        ('contributors', 'Katkıda Bulunanlar'),
    ]
    section = models.CharField('Bölüm', max_length=20, choices=SECTION_CHOICES)
    label = models.CharField('Görünen ad', max_length=100)
    url = models.CharField('Bağlantı', max_length=500, validators=[validate_footer_url])
    sort_order = models.PositiveSmallIntegerField('Sıra', default=0)
    is_active = models.BooleanField('Yayında', default=True)
    open_new_tab = models.BooleanField('Yeni sekmede aç', default=False)

    class Meta:
        ordering = ['section', 'sort_order', 'pk']
        verbose_name = 'Footer bağlantısı'
        verbose_name_plural = 'Footer bağlantıları'

    def __str__(self):
        return f'{self.get_section_display()} · {self.label}'


class AuditLog(models.Model):
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='audit_events',
    )
    action = models.CharField(max_length=100, db_index=True)
    target_type = models.CharField(max_length=120, blank=True)
    target_id = models.CharField(max_length=80, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    client_hash = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['target_type', 'target_id'], name='audit_target_idx')]

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError('Audit log kayıtları değiştirilemez.')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Audit log kayıtları silinemez.')

    def __str__(self):
        return f'{self.action} / {self.target_type}:{self.target_id}'


class Notification(models.Model):
    TYPE_CHOICES = [
        ('project_comment', 'Proje yorumu'),
        ('project_update', 'Proje güncellemesi'),
        ('project_approved', 'Proje onayı'),
        ('application_accepted', 'Başvuru kabulü'),
        ('application_rejected', 'Başvuru reddi'),
        ('mentorship_request', 'Mentorluk talebi'),
        ('opportunity', 'Kariyer ilanı'),
        ('event', 'Etkinlik'),
        ('system', 'Sistem'),
        ('team_invite', 'Ekip daveti'),
        ('team_invite_result', 'Ekip daveti sonucu'),
        ('project_like_milestone', 'Proje beğeni eşiği'),
        ('project_featured', 'Proje öne çıkarıldı'),
        ('website_review', 'Kişisel web sitesi incelemesi'),
        ('alumni_registration', 'Mezun kayıt talebi'),
        ('moderation', 'Moderasyon'),
        ('pending_task', 'Bekleyen yönetim görevi'),
    ]

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notifications',
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='notifications_created',
    )
    notification_type = models.CharField(max_length=32, choices=TYPE_CHOICES, db_index=True)
    title = models.CharField(max_length=120, blank=True)
    message = models.CharField(max_length=300)
    target_url = models.CharField(max_length=500, blank=True)
    dedupe_key = models.CharField(max_length=160, blank=True)
    read_at = models.DateTimeField(blank=True, null=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['recipient', 'read_at', '-created_at'], name='notification_inbox_idx'),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['recipient', 'dedupe_key'],
                condition=~models.Q(dedupe_key=''),
                name='unique_notification_dedupe_key',
            ),
        ]

    def clean(self):
        super().clean()
        if self.target_url and (not self.target_url.startswith('/') or self.target_url.startswith('//')):
            raise ValidationError('Bildirim hedefi yalnızca güvenli bir site içi adres olabilir.')

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def is_read(self):
        return self.read_at is not None

    def __str__(self):
        return f'{self.recipient}: {self.message}'


class AnalyticsEvent(models.Model):
    EVENT_CHOICES = [
        ('profile_view', 'Profil görüntüleme'),
        ('demo_click', 'Demo tıklama'),
        ('github_click', 'GitHub tıklama'),
        ('event_registration', 'Etkinlik kaydı'),
        ('mentorship_request', 'Mentorluk talebi'),
        ('search', 'Arama'),
        ('ai_answer', 'AI yanıtı'),
        ('company_contact', 'Şirket iletişim talebi'),
    ]

    event_type = models.CharField(max_length=32, choices=EVENT_CHOICES, db_index=True)
    target_type = models.CharField(max_length=80, blank=True)
    target_id = models.CharField(max_length=80, blank=True)
    visitor_hash = models.CharField(max_length=64)
    succeeded = models.BooleanField(blank=True, null=True)
    metadata = models.JSONField(default=dict, blank=True)
    date_bucket = models.DateField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['event_type', 'target_type', 'target_id', 'visitor_hash', 'date_bucket'],
                name='unique_daily_analytics_event',
            ),
        ]
        indexes = [models.Index(fields=['event_type', 'date_bucket'], name='analytics_type_date_idx')]

    def __str__(self):
        return f'{self.event_type} · {self.date_bucket}'
