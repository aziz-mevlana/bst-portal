import secrets

from django.db import models
from django.contrib.auth.models import User
from django.core.validators import MaxValueValidator, MinValueValidator
from django.utils import timezone


def generate_checkin_token():
    return secrets.token_urlsafe(32)

class Event(models.Model):
    EVENT_TYPE_CHOICES = [
        ('seminar', 'Seminer'),
        ('workshop', 'Atölye'),
        ('conference', 'Konferans'),
        ('social', 'Sosyal Etkinlik'),
        ('other', 'Diğer'),
    ]

    title = models.CharField(max_length=200)
    description = models.TextField()
    event_type = models.CharField(max_length=20, choices=EVENT_TYPE_CHOICES)
    location = models.CharField(max_length=200)
    start_date = models.DateTimeField()
    end_date = models.DateTimeField()
    image = models.ImageField(upload_to='events/', blank=True, null=True)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='created_events')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)
    allow_registration = models.BooleanField(default=False)
    capacity = models.PositiveIntegerField(blank=True, null=True)
    registration_deadline = models.DateTimeField(blank=True, null=True)
    waitlist_enabled = models.BooleanField(default=True)
    certificate_enabled = models.BooleanField(default=False)

    class Meta:
        ordering = ['-start_date']

    def __str__(self):
        return self.title

    @property
    def registration_is_open(self):
        now = timezone.now()
        return bool(
            self.is_active
            and self.allow_registration
            and self.start_date > now
            and (self.registration_deadline is None or self.registration_deadline >= now)
        )

    @property
    def registered_count(self):
        return self.registrations.filter(status__in=['registered', 'attended']).count()

    @property
    def available_spots(self):
        if self.capacity is None:
            return None
        return max(0, self.capacity - self.registered_count)


class EventRegistration(models.Model):
    STATUS_CHOICES = [
        ('registered', 'Kayıtlı'),
        ('waitlisted', 'Bekleme listesinde'),
        ('attended', 'Katıldı'),
        ('cancelled', 'İptal edildi'),
    ]

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='registrations')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='event_registrations')
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default='registered')
    checkin_token = models.CharField(max_length=64, unique=True, default=generate_checkin_token, editable=False)
    checked_in_at = models.DateTimeField(blank=True, null=True)
    feedback_rating = models.PositiveSmallIntegerField(blank=True, null=True, validators=[MinValueValidator(1), MaxValueValidator(5)])
    feedback_comment = models.TextField(blank=True)
    feedback_at = models.DateTimeField(blank=True, null=True)
    certificate_eligible = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['created_at']
        constraints = [models.UniqueConstraint(fields=['event', 'user'], name='unique_event_user_registration')]
        indexes = [models.Index(fields=['event', 'status', 'created_at'], name='event_registration_queue_idx')]

    def __str__(self):
        return f'{self.event} · {self.user} · {self.status}'
