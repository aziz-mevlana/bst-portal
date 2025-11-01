from django.db import models
from django.contrib.auth.models import User


class News(models.Model):
    title = models.CharField(max_length=200, verbose_name="Başlık")
    summary = models.TextField(verbose_name="Özet")
    content = models.TextField(verbose_name="İçerik")
    source = models.CharField(max_length=100, verbose_name="Kaynak")
    url = models.URLField(blank=True, null=True, verbose_name="Haber Linki")
    date = models.DateTimeField(auto_now_add=True, verbose_name="Tarih")
    image = models.ImageField(upload_to='news/', blank=True, null=True, verbose_name="Görsel")
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="Oluşturan")
    news_type = models.CharField(max_length=100, verbose_name="Haber Tipi", null=True, blank=True)
    news_category = models.CharField(max_length=100, verbose_name="Haber Kategorisi", null=True, blank=True)
    is_homepage = models.BooleanField(default=False, verbose_name="Anasayfa")

    def __str__(self):
        return self.title
