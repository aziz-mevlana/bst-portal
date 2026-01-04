from django.db import models
from django.contrib.auth.models import User


class Article(models.Model):
    """News articles and announcements"""
    title = models.CharField(max_length=200, verbose_name="Title")
    summary = models.TextField(verbose_name="Summary")
    content = models.TextField(verbose_name="Content")
    source = models.CharField(max_length=100, verbose_name="Source")
    url = models.URLField(blank=True, null=True, verbose_name="Article URL")
    date = models.DateTimeField(auto_now_add=True, verbose_name="Date")
    image = models.ImageField(upload_to='articles/', blank=True, null=True, verbose_name="Image")
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="Created By")
    article_type = models.CharField(max_length=100, verbose_name="Article Type", null=True, blank=True)
    article_category = models.CharField(max_length=100, verbose_name="Article Category", null=True, blank=True)
    is_homepage = models.BooleanField(default=False, verbose_name="Show on Homepage")

    class Meta:
        verbose_name = "Article"
        verbose_name_plural = "Articles"
        ordering = ['-date']

    def __str__(self):
        return self.title



