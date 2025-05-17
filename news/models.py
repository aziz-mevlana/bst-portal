from django.db import models
from django.utils import timezone

class NewsItem(models.Model):
    title = models.CharField(max_length=200, verbose_name="Başlık")
    summary = models.TextField(verbose_name="Özet")
    content = models.TextField(verbose_name="İçerik")
    date = models.DateTimeField(default=timezone.now, verbose_name="Tarih")
    source = models.CharField(max_length=100, verbose_name="Kaynak")
    url = models.URLField(blank=True, null=True, verbose_name="Kaynak URL")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Oluşturulma Tarihi")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Güncellenme Tarihi")

    class Meta:
        verbose_name = "Haber"
        verbose_name_plural = "Haberler"
        ordering = ['-date']

    def __str__(self):
        return self.title 