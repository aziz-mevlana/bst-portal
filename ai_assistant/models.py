from django.db import models
from django.contrib.auth.models import User


class KnowledgeSource(models.Model):
    """Bilgi kaynagi - asistanin bilgileri aldigi dokumanlar"""

    CATEGORY_CHOICES = [
        ('academic', 'Akademik'),
        ('internship', 'Staj'),
        ('course', 'Ders'),
        ('project', 'Proje'),
        ('general', 'Genel'),
    ]

    title = models.CharField(max_length=200, verbose_name="Baslik")
    description = models.TextField(verbose_name="Aciklama", blank=True)
    content = models.TextField(verbose_name="Icerik", help_text="Dokumanin metin icerigi")
    category = models.CharField(max_length=50, choices=CATEGORY_CHOICES, default='general', verbose_name="Kategori")
    source_file = models.FileField(upload_to='knowledge/', blank=True, null=True, verbose_name="Dosya")
    is_active = models.BooleanField(default=True, verbose_name="Aktif")
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="Olusturan", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Olusturma Tarihi")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Guncelleme Tarihi")

    class Meta:
        verbose_name = "Bilgi Kaynagi"
        verbose_name_plural = "Bilgi Kaynaklari"
        ordering = ['category', 'title']

    def __str__(self):
        return f"{self.title} ({self.get_category_display()})"
