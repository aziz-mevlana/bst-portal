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

class News(models.Model):
    CATEGORY_CHOICES = [
        ('tech', 'Teknoloji'),
        ('education', 'Eğitim'),
        ('career', 'Kariyer'),
        ('other', 'Diğer'),
    ]

    title = models.CharField(max_length=200)
    content = models.TextField()
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    image = models.ImageField(upload_to='news/', blank=True, null=True)
    source_url = models.URLField(blank=True, null=True)
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name='news')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_published = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = 'News'
        ordering = ['-created_at']

    def __str__(self):
        return self.title
