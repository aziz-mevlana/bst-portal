from django.db import models
from django.contrib.auth.models import User


class NewsKeyword(models.Model):
    """Anahtar kelimeler - haber çekmek için"""
    keyword = models.CharField(max_length=100, verbose_name="Anahtar Kelime")
    is_active = models.BooleanField(default=True, verbose_name="Aktif")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Haber Anahtar Kelimesi"
        verbose_name_plural = "Haber Anahtar Kelimeleri"
        ordering = ['keyword']

    def __str__(self):
        return self.keyword


class Article(models.Model):
    """News articles and announcements"""

    CATEGORY_CHOICES = [
        ('technology', 'Teknoloji'),
        ('university', 'Üniversite'),
        ('software', 'Yazılım'),
        ('sector', 'Sektörel'),
    ]

    title = models.CharField(max_length=200, verbose_name="Başlık")
    summary = models.TextField(verbose_name="Özet")
    content = models.TextField(verbose_name="İçerik")
    source = models.CharField(max_length=100, verbose_name="Kaynak", blank=True)
    url = models.URLField(blank=True, null=True, verbose_name="Haber URL")
    source_url = models.URLField(blank=True, verbose_name="Kaynak URL")
    date = models.DateTimeField(auto_now_add=True, verbose_name="Tarih")
    image = models.ImageField(upload_to='articles/', blank=True, null=True, verbose_name="Görsel")
    image_url = models.URLField(blank=True, verbose_name="Görsel URL")
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="Oluşturan", null=True, blank=True)
    article_type = models.CharField(max_length=100, verbose_name="Haber Türü", null=True, blank=True)
    article_category = models.CharField(max_length=100, verbose_name="Kategori", null=True, blank=True)
    category = models.CharField(max_length=50, choices=CATEGORY_CHOICES, blank=True, null=True, verbose_name="AI Kategori")
    is_homepage = models.BooleanField(default=False, verbose_name="Anasayfada Göster")
    is_approved = models.BooleanField(default=False, verbose_name="Onaylı")

    class Meta:
        verbose_name = "Haber"
        verbose_name_plural = "Haberler"
        ordering = ['-date']

    def __str__(self):
        return self.title



