from django.db import models
from django.contrib.auth.models import User

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

    class Meta:
        ordering = ['-start_date']

    def __str__(self):
        return self.title