from django.db import models
from django.contrib.auth.models import User
import hashlib


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


class ChatCache(models.Model):
    """Onceden cevaplanmis sorularin onbellegi"""
    
    question = models.TextField(verbose_name="Soru", unique=True)
    question_hash = models.CharField(max_length=64, verbose_name="Soru Hash", db_index=True)
    response = models.TextField(verbose_name="Cevap")
    sources_used = models.JSONField(default=list, verbose_name="Kullanilan Kaynaklar")
    hit_count = models.PositiveIntegerField(default=0, verbose_name="Kullanim Sayisi")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Olusturma Tarihi")
    last_used_at = models.DateTimeField(auto_now=True, verbose_name="Son Kullanim Tarihi")
    is_active = models.BooleanField(default=True, verbose_name="Aktif")

    class Meta:
        verbose_name = "Chat Onbellek"
        verbose_name_plural = "Chat Onbellek"
        ordering = ['-hit_count', '-last_used_at']

    def __str__(self):
        return f"{self.question[:50]}... ({self.hit_count} kez)"

    @staticmethod
    def get_hash(question):
        """Sorunun hash degerini hesapla"""
        return hashlib.md5(question.lower().strip().encode('utf-8')).hexdigest()

    @classmethod
    def get_cached_response(cls, question):
        """Cache'den cevap al"""
        q_hash = cls.get_hash(question)
        try:
            cache = cls.objects.get(question_hash=q_hash, is_active=True)
            cache.hit_count += 1
            cache.save(update_fields=['hit_count', 'last_used_at'])
            return {
                'response': cache.response,
                'sources_used': cache.sources_used,
                'cached': True
            }
        except cls.DoesNotExist:
            return None

    @classmethod
    def save_to_cache(cls, question, response, sources_used):
        """Cevabi cache'e kaydet"""
        q_hash = cls.get_hash(question)
        cls.objects.update_or_create(
            question_hash=q_hash,
            defaults={
                'question': question,
                'response': response,
                'sources_used': sources_used,
                'is_active': True
            }
        )
