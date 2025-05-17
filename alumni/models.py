from django.db import models
from django.contrib.auth.models import User

class Tag(models.Model):
    name = models.CharField(max_length=50, unique=True)
    description = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

class AlumniProfile(models.Model):
    EXPERIENCE_LEVEL_CHOICES = [
        ('junior', 'Junior (0-2 yıl)'),
        ('mid', 'Mid-Level (2-5 yıl)'),
        ('senior', 'Senior (5+ yıl)'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='alumni_profile')
    graduation_year = models.IntegerField()
    current_position = models.CharField(max_length=200)
    company = models.CharField(max_length=200)
    experience_level = models.CharField(max_length=10, choices=EXPERIENCE_LEVEL_CHOICES)
    bio = models.TextField()
    linkedin_url = models.URLField(blank=True, null=True)
    github_url = models.URLField(blank=True, null=True)
    personal_website = models.URLField(blank=True, null=True)
    tags = models.ManyToManyField(Tag, related_name='alumni')
    is_available_for_mentoring = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-graduation_year']

    def __str__(self):
        return f"{self.user.get_full_name()} - {self.graduation_year}"

class AlumniExperience(models.Model):
    alumni = models.ForeignKey(AlumniProfile, on_delete=models.CASCADE, related_name='experiences')
    company = models.CharField(max_length=200)
    position = models.CharField(max_length=200)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    is_current = models.BooleanField(default=False)
    description = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-start_date']

    def __str__(self):
        return f"{self.position} at {self.company}"
