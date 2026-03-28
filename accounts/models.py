import random
from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from datetime import timedelta
from projects.models import ProjectCategory, Technology


class EmailVerification(models.Model):
    email = models.EmailField()
    code = models.CharField(max_length=6)
    session_data = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    is_verified = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Email Verification"
        verbose_name_plural = "Email Verifications"

    def __str__(self):
        return f"{self.email} - {self.code}"

    def is_expired(self):
        return timezone.now() > self.created_at + timedelta(minutes=10)

    @staticmethod
    def generate_code():
        return str(random.randint(100000, 999999))


class PasswordReset(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    code = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    is_used = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Password Reset"
        verbose_name_plural = "Password Resets"

    def is_expired(self):
        return timezone.now() > self.created_at + timedelta(minutes=10)

    @staticmethod
    def generate_code():
        return str(random.randint(100000, 999999))


class Profile(models.Model):
    """User profile information"""
    USER_TYPE_CHOICES = [
        ('student', 'Öğrenci'),
        ('teacher', 'Öğretim Üyesi'),
        ('alumni', 'Mezun'),
        ('staff_student', 'Görevli Öğrenci')
    ]
    
    CLASS_CHOICES = [
        ('1', '1. Sınıf'),
        ('2', '2. Sınıf'),
        ('3', '3. Sınıf'),
        ('4', '4. Sınıf'),
        ('alt', 'Altdan Devam Ediyor'),
        ('bitir', 'Bitirdi')
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    user_type = models.CharField(max_length=15, choices=USER_TYPE_CHOICES, default='student')
    username = models.CharField(max_length=150, unique=True, blank=True, null=True)
    first_name = models.CharField(max_length=30, blank=True, null=True)
    last_name = models.CharField(max_length=30, blank=True, null=True)
    student_number = models.CharField(max_length=20, blank=True, null=True)
    class_level = models.CharField(max_length=20, choices=CLASS_CHOICES, default='1')
    department = models.CharField(max_length=100, blank=True, null=True, default='Bilişim Sistemleri ve Teknolojileri')
    phone_number = models.CharField(max_length=15, blank=True, null=True)
    profile_picture = models.ImageField(upload_to='profile_pictures/', blank=True, null=True)
    
    # Skills and Technologies
    categories = models.ManyToManyField(ProjectCategory, related_name='student_profiles', blank=True)
    technologies = models.ManyToManyField(Technology, related_name='student_profiles', blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Profile"
        verbose_name_plural = "Profiles"

    def __str__(self):
        return f"{self.user.get_full_name()} - {self.get_user_type_display()}"

# Keep old model for backward compatibility during migration
class UserProfile(models.Model):
    """Deprecated: Use Profile instead"""
    USER_TYPE_CHOICES = [
        ('student', 'Öğrenci'),
        ('teacher', 'Öğretim Üyesi'),
        ('alumni', 'Mezun'),
        ('staff_student', 'Görevli Öğrenci')
    ]
    
    CLASS_CHOICES = [
        ('1', '1. Sınıf'),
        ('2', '2. Sınıf'),
        ('3', '3. Sınıf'),
        ('4', '4. Sınıf'),
        ('alt', 'Altdan Devam Ediyor'),
        ('bitir', 'Bitirdi')
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='old_profile')
    user_type = models.CharField(max_length=15, choices=USER_TYPE_CHOICES, default='student')
    username = models.CharField(max_length=150, unique=True, blank=True, null=True)
    first_name = models.CharField(max_length=30, blank=True, null=True)
    last_name = models.CharField(max_length=30, blank=True, null=True)
    student_number = models.CharField(max_length=20, blank=True, null=True)
    class_level = models.CharField(max_length=20, choices=CLASS_CHOICES, default='1')
    department = models.CharField(max_length=100, blank=True, null=True, default='Bilişim Sistemleri ve Teknolojileri')
    phone_number = models.CharField(max_length=15, blank=True, null=True)
    profile_picture = models.ImageField(upload_to='profile_pictures/', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.get_full_name()} - {self.get_user_type_display()}"

# Signal handlers
@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.create(user=instance)

@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    instance.profile.save()
