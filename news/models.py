from django.db import models

# Create your models here.

class News(models.Model):
    title = models.CharField(max_length=200, verbose_name="Başlık")
    summary = models.TextField(verbose_name="Özet")
    content = models.TextField(verbose_name="İçerik")
    source = models.CharField(max_length=100, verbose_name="Kaynak")
    url = models.URLField(blank=True, null=True, verbose_name="Haber Linki")
    date = models.DateTimeField(auto_now_add=True, verbose_name="Tarih")
    image = models.ImageField(upload_to='news/', blank=True, null=True, verbose_name="Görsel")

    class Meta:
        verbose_name = "Haber"
        verbose_name_plural = "Haberler"
        ordering = ['-date']

    def __str__(self):
        return self.title
