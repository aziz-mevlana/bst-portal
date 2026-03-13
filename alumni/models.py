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

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='alumni')
    graduation_year = models.IntegerField(default=datetime.now().year, blank=True, null=True)
    current_position = models.CharField(max_length=200)
    company = models.CharField(max_length=200)
    experience_level = models.CharField(max_length=15, choices=EXPERIENCE_LEVEL_CHOICES)
    bio = models.TextField()
    linkedin_url = models.URLField(blank=True, null=True)
    github_url = models.URLField(blank=True, null=True)
    personal_website = models.URLField(blank=True, null=True)
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
        return f"{self.user.get_full_name()} - {self.graduation_year}"


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


# Keep old models for backward compatibility during migration
class Tag(models.Model):
    """Deprecated: Use SkillTag instead"""
    name = models.CharField(max_length=50, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class AlumniProfile(models.Model):
    """Deprecated: Use Alumni instead"""
    EXPERIENCE_LEVEL_CHOICES = [
        ('junior', 'Junior'),
        ('mid', 'Mid-Level'),
        ('senior', 'Senior'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='old_alumni_profile')
    graduation_year = models.IntegerField(default=datetime.now().year, blank=True, null=True)
    current_position = models.CharField(max_length=200)
    company = models.CharField(max_length=200)
    experience_level = models.CharField(max_length=10, choices=EXPERIENCE_LEVEL_CHOICES)
    bio = models.TextField()
    linkedin_url = models.URLField(blank=True, null=True)
    github_url = models.URLField(blank=True, null=True)
    personal_website = models.URLField(blank=True, null=True)
    tags = models.ManyToManyField(Tag, related_name='old_alumni')
    is_available_for_mentoring = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_show_in_alumni_list = models.BooleanField(default=True)

    class Meta:
        ordering = ['-graduation_year']
        
    def __str__(self):
        return f"{self.user.get_full_name()} - {self.graduation_year}"


class AlumniExperience(models.Model):
    """Deprecated: Use WorkExperience instead"""
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
