from django.db import models
from django.contrib.auth.models import User
import hashlib
from django.utils import timezone


class KnowledgeSource(models.Model):
    """Bilgi kaynagi - asistanin bilgileri aldigi dokumanlar"""

    CATEGORY_CHOICES = [
        ('academic', 'Akademik'),
        ('internship', 'Staj'),
        ('course', 'Ders'),
        ('project', 'Proje'),
        ('general', 'Genel'),
    ]
    AUDIENCE_CHOICES = [
        ('all', 'Tüm giriş yapmış kullanıcılar'),
        ('student', 'Yalnızca öğrenciler'),
        ('teacher', 'Yalnızca akademisyenler'),
        ('alumni', 'Yalnızca mezunlar'),
        ('staff', 'Yalnızca yöneticiler'),
    ]

    title = models.CharField(max_length=200, verbose_name="Baslik")
    description = models.TextField(verbose_name="Aciklama", blank=True)
    content = models.TextField(verbose_name="Icerik", help_text="Dokumanin metin icerigi")
    category = models.CharField(max_length=50, choices=CATEGORY_CHOICES, default='general', verbose_name="Kategori")
    audience = models.CharField(max_length=12, choices=AUDIENCE_CHOICES, default='all', db_index=True)
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

    def save(self, *args, **kwargs):
        result = super().save(*args, **kwargs)
        ChatCache.objects.all().delete()
        return result

    def delete(self, *args, **kwargs):
        result = super().delete(*args, **kwargs)
        ChatCache.objects.all().delete()
        return result


class ChatCache(models.Model):
    """Onceden cevaplanmis sorularin onbellegi"""
    
    question = models.TextField(verbose_name="Soru")
    question_hash = models.CharField(max_length=64, verbose_name="Soru Hash", db_index=True)
    audience_key = models.CharField(max_length=20, default='all', db_index=True)
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
        constraints = [
            models.UniqueConstraint(fields=['question_hash', 'audience_key'], name='unique_ai_cache_audience'),
        ]

    def __str__(self):
        return f"{self.question[:50]}... ({self.hit_count} kez)"

    @staticmethod
    def get_hash(question):
        """Sorunun hash degerini hesapla"""
        return hashlib.sha256(question.lower().strip().encode('utf-8')).hexdigest()

    @classmethod
    def get_cached_response(cls, question, audience_key='all'):
        """Cache'den cevap al"""
        q_hash = cls.get_hash(question)
        try:
            cache = cls.objects.get(question_hash=q_hash, audience_key=audience_key, is_active=True)
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
    def save_to_cache(cls, question, response, sources_used, audience_key='all'):
        """Cevabi cache'e kaydet"""
        q_hash = cls.get_hash(question)
        cls.objects.update_or_create(
            question_hash=q_hash,
            audience_key=audience_key,
            defaults={
                'question': question,
                'response': response,
                'sources_used': sources_used,
                'is_active': True
            }
        )


class UnansweredQuestion(models.Model):
    question_hash = models.CharField(max_length=64, unique=True)
    safe_summary = models.CharField(max_length=180)
    ask_count = models.PositiveIntegerField(default=1)
    roles = models.JSONField(default=dict, blank=True)
    first_asked_at = models.DateTimeField(auto_now_add=True)
    last_asked_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ['-ask_count', '-last_asked_at']

    def mark_resolved(self):
        self.resolved_at = timezone.now()
        self.save(update_fields=['resolved_at'])

    def __str__(self):
        return f'{self.safe_summary} ({self.ask_count})'
