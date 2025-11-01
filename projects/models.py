from django.db import models
from django.contrib.auth.models import User


class Request(models.Model):
    """Teacher creates a Request that students can respond to."""
    title = models.CharField(max_length=200)
    course = models.CharField(max_length=200, blank=True, null=True)
    duration = models.CharField(max_length=100, blank=True, null=True)
    team_size = models.PositiveSmallIntegerField(blank=True, null=True)
    teacher = models.ForeignKey(User, on_delete=models.CASCADE, related_name='requests')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} - {self.teacher.get_full_name()}"


class Respons(models.Model):
    """Student response to a Request. Central model holding project info."""
    request = models.ForeignKey(Request, on_delete=models.CASCADE, related_name='responses')
    title = models.CharField(max_length=200)
    advisor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='advised_responses')
    description = models.TextField(blank=True, null=True)
    team = models.ManyToManyField(User, related_name='responses', blank=True)
    project_link = models.URLField(blank=True, null=True)
    status = models.CharField(max_length=50, default='draft')
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='created_responses')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} - {self.created_by.get_full_name()}"


class ResponsUpdate(models.Model):
    """Updates linked to a Respons (progress, state changes)."""
    respons = models.ForeignKey(Respons, on_delete=models.CASCADE, related_name='updates')
    which_respons = models.CharField(max_length=200, blank=True, null=True)
    when = models.DateTimeField(blank=True, null=True)
    project_status = models.CharField(max_length=100, blank=True, null=True)
    notify_teacher = models.BooleanField(default=False)
    note = models.TextField(blank=True, null=True)
    updated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-updated_at']

    def __str__(self):
        return f"Update for {self.respons.title} at {self.updated_at}"


class Comment(models.Model):
    """Comments attached to a Respons."""
    respons = models.ForeignKey(Respons, on_delete=models.CASCADE, related_name='comments')
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name='respons_comments')
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"Comment by {self.author.get_full_name()} on {self.respons.title}"
