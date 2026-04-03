from django.db import models
from django.contrib.auth.models import User


class ProjectCategory(models.Model):
    """Project category/type (what kind of project it is)"""
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    color = models.CharField(max_length=7, default='#3B82F6', help_text='Hex color code')
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = "Project Category"
        verbose_name_plural = "Project Categories"
        ordering = ['name']
    
    def __str__(self):
        return self.name


class Technology(models.Model):
    """Technologies used in projects"""
    name = models.CharField(max_length=100, unique=True)
    icon = models.CharField(max_length=50, blank=True, help_text='Font Awesome icon class')
    color = models.CharField(max_length=7, default='#10B981', help_text='Hex color code')
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = "Technology"
        verbose_name_plural = "Technologies"
        ordering = ['name']
    
    def __str__(self):
        return self.name


class ProjectRequest(models.Model):
    """Project requests/proposals"""
    SEMESTER_CHOICES = [
        ('fall', 'Güz'),
        ('spring', 'Bahar'),
        ('summer', 'Yaz'),
    ]
    REQUEST_STATUS_CHOICES = [
        ('active', 'Aktif'),
        ('closed', 'Kapandı'),
        ('completed', 'Tamamlandı'),
    ]
    SUPERVISION_CHOICES = [
        ('unsupervised', 'Denetimsiz'),
        ('supervised', 'Denetimli'),
    ]

    title = models.CharField(max_length=200)
    course = models.CharField(max_length=200, blank=True, null=True)
    description = models.TextField(blank=True, null=True, verbose_name='Açıklama')
    requirements = models.TextField(blank=True, null=True, verbose_name='Gerekli Koşullar')
    semester = models.CharField(max_length=10, choices=SEMESTER_CHOICES, blank=True, null=True, verbose_name='Dönem')
    year = models.PositiveSmallIntegerField(blank=True, null=True, verbose_name='Yıl')
    deadline = models.DateField(blank=True, null=True, verbose_name='Son Başvuru Tarihi')
    team_size = models.PositiveSmallIntegerField(blank=True, null=True)
    status = models.CharField(max_length=15, choices=REQUEST_STATUS_CHOICES, default='active', verbose_name='Durum')
    supervision_type = models.CharField(max_length=15, choices=SUPERVISION_CHOICES, default='unsupervised', verbose_name='Denetim Türü')
    teacher = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, related_name='project_requests')
    categories = models.ManyToManyField(ProjectCategory, related_name='project_requests', blank=True, verbose_name='Kategoriler')
    technologies = models.ManyToManyField(Technology, related_name='project_requests', blank=True, verbose_name='Teknolojiler')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Project Request"
        verbose_name_plural = "Project Requests"

    def __str__(self):
        if self.teacher:
            return f"{self.title} - {self.teacher.get_full_name()}"
        else:
            return self.title

    def get_semester_display_full(self):
        if self.semester:
            return self.get_semester_display()
        return None

    @property
    def is_past_deadline(self):
        if self.deadline:
            from django.utils import timezone
            return timezone.now().date() > self.deadline
        return False


class Project(models.Model):
    """Main project model"""
    STATUS_CHOICES = [
        ('draft', 'Taslak'),
        ('in_review', 'Değerlendirme Aşamasında'),
        ('approved', 'Fikir Onaylandı'),
        ('in_progress', 'Devam Ediyor'),
        ('completed', 'Tamamlandı'),
    ]
    project_request = models.ForeignKey(ProjectRequest, on_delete=models.CASCADE, related_name='projects')
    title = models.CharField(max_length=200)
    advisor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='advised_projects')
    description = models.TextField(blank=True, null=True)
    team = models.ManyToManyField(User, related_name='projects', blank=True)
    project_link = models.URLField(blank=True, null=True)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='created_projects')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    is_private = models.BooleanField(default=False)

    # Tag relationships
    categories = models.ManyToManyField(ProjectCategory, related_name='projects', blank=True)
    technologies = models.ManyToManyField(Technology, related_name='projects', blank=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Project"
        verbose_name_plural = "Projects"

    def __str__(self):
        return f"{self.title} - {self.created_by.get_full_name()}"


class ProjectFeedback(models.Model):
    """Teacher feedback for supervised projects"""
    project = models.OneToOneField(Project, on_delete=models.CASCADE, related_name='feedback')
    teacher = models.ForeignKey(User, on_delete=models.CASCADE, related_name='project_feedbacks')
    content = models.TextField(verbose_name='Geri Bildirim')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Project Feedback"
        verbose_name_plural = "Project Feedbacks"

    def __str__(self):
        return f"Feedback for {self.project.title} by {self.teacher.get_full_name()}"


class ProjectUpdate(models.Model):
    """Updates for projects"""
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='updates')
    title = models.CharField(max_length=200, blank=True, null=True)
    note = models.TextField(blank=True, null=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='project_updates')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Project Update"
        verbose_name_plural = "Project Updates"

    def __str__(self):
        return f"Update for {self.project.title} at {self.created_at}"


class ProjectComment(models.Model):
    """Comments on projects"""
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='comments')
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name='project_comments')
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        verbose_name = "Project Comment"
        verbose_name_plural = "Project Comments"

    def __str__(self):
        return f"Comment by {self.author.get_full_name()} on {self.project.title}"
