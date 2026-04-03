from django.db import models
from django.contrib.auth.models import User
from datetime import datetime
from projects.models import ProjectCategory, Technology


class Alumni(models.Model):
    """Alumni profile information"""
    EXPERIENCE_LEVEL_CHOICES = [
        ('junior', 'Junior'),
        ('mid_level', 'Mid-Level'),
        ('senior', 'Senior'),
    ]

    user = models.OneToOneField(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='alumni')
    full_name = models.CharField(max_length=200, blank=True, default='')
    graduation_year = models.IntegerField(default=datetime.now().year, blank=True, null=True)
    current_position = models.CharField(max_length=200, blank=True, default='')
    company = models.CharField(max_length=200, blank=True, default='')
    experience_level = models.CharField(max_length=15, choices=EXPERIENCE_LEVEL_CHOICES, blank=True, default='junior')
    bio = models.TextField(blank=True, default='')
    linkedin_url = models.URLField(blank=True, null=True)
    github_url = models.URLField(blank=True, null=True)
    personal_website = models.URLField(blank=True, null=True)
    profile_photo = models.CharField(max_length=500, blank=True, default='')
    categories = models.ManyToManyField(ProjectCategory, related_name='alumni_members', blank=True)
    technologies = models.ManyToManyField(Technology, related_name='alumni_members', blank=True)
    is_available_for_mentoring = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_show_in_alumni_list = models.BooleanField(default=True)

    class Meta:
        ordering = ['-graduation_year']
        verbose_name = "Alumni"
        verbose_name_plural = "Alumni"
        
    def __str__(self):
        if self.user:
            return f"{self.user.get_full_name()} - {self.graduation_year}"
        return f"{self.full_name} - {self.graduation_year}"

    def get_display_name(self):
        if self.user:
            return self.user.get_full_name()
        return self.full_name or 'İsimsiz Mezun'

    def get_profile_photo_url(self):
        if self.user and hasattr(self.user, 'profile') and self.user.profile.profile_picture:
            return self.user.profile.profile_picture.url
        if self.profile_photo:
            filename = self.profile_photo.split('\\')[-1] if '\\' in self.profile_photo else self.profile_photo
            return f'/linkedin_profile_photos/{filename}'
        return None


class WorkExperience(models.Model):
    """Work experience for alumni (can be reused for other purposes)"""
    person = models.ForeignKey(Alumni, on_delete=models.CASCADE, related_name='work_experiences')
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
        verbose_name = "Work Experience"
        verbose_name_plural = "Work Experiences"

    def __str__(self):
        return f"{self.position} at {self.company}"
