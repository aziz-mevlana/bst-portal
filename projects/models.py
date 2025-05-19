from django.db import models
from django.contrib.auth.models import User

class Project(models.Model):
    STATUS_CHOICES = [
        ('planning', 'Planlama'),
        ('in_progress', 'Devam Ediyor'),
        ('completed', 'Tamamlandı'),
        ('on_hold', 'Beklemede'),
    ]

    CATEGORY_CHOICES = [
        ('research', 'Araştırma'),
        ('development', 'Geliştirme'),
        ('design', 'Tasarım'),
        ('other', 'Diğer'),
    ]

    title = models.CharField(max_length=200, verbose_name='Proje Başlığı')
    description = models.TextField(verbose_name='Proje Açıklaması')
    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name='student_projects', verbose_name='Öğrenci')
    supervisor = models.ForeignKey(User, on_delete=models.CASCADE, related_name='supervised_projects', verbose_name='Danışman')
    project_url = models.URLField(blank=True, null=True, verbose_name='Proje URL')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='planning', verbose_name='Durum')
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='other', verbose_name='Kategori')
    start_date = models.DateField(verbose_name='Başlangıç Tarihi')
    deadline = models.DateField(verbose_name='Bitiş Tarihi')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_public = models.BooleanField(default=False, verbose_name='Herkese Açık')
    team_members = models.ManyToManyField(User, related_name='team_projects', blank=True, verbose_name='Takım Üyeleri')
    attachments = models.FileField(upload_to='project_attachments/', blank=True, null=True, verbose_name='Ekler')

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Proje'
        verbose_name_plural = 'Projeler'

    def __str__(self):
        return f"{self.title} - {self.student.get_full_name()}"

class ProjectUpdate(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='updates')
    title = models.CharField(max_length=200)
    content = models.TextField()
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='project_updates')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.project.title} - {self.title}"

class ProjectComment(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='comments')
    content = models.TextField()
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name='project_comments')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"Yorum by {self.author.get_full_name()} on {self.project.title}"
