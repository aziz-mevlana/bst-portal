from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.db.models import Q
import logging
import re
from pypdf.errors import PdfReadError
from .models import KnowledgeSource
from .gemini_service import get_gemini_response
from .analytics import record_unanswered_question
from .pdf_utils import extract_text_from_pdf
from core.rate_limit import is_rate_limited
from core.audit import record_audit_event
from core.analytics import record_analytics_event
from django.views.decorators.http import require_POST


logger = logging.getLogger(__name__)
MAX_SOURCE_FILE_SIZE = 10 * 1024 * 1024
import json


def can_manage_knowledge_sources(user):
    """Knowledge-source contents are administrative data, not role-level content."""

    return bool(user.is_authenticated and (user.is_staff or user.is_superuser))


def audience_key_for_user(user):
    if user.is_staff or user.is_superuser:
        return 'staff'
    role = getattr(getattr(user, 'profile', None), 'user_type', 'all')
    return role if role in {'student', 'teacher', 'alumni'} else 'all'


def authorized_sources_for_user(user):
    sources = KnowledgeSource.objects.filter(is_active=True)
    audience_key = audience_key_for_user(user)
    if audience_key == 'staff':
        return sources
    return sources.filter(Q(audience='all') | Q(audience=audience_key))


def filter_relevant_sources(sources, query):
    """Soruya gore ilgili kaynaklari filtrele"""
    query_lower = query.casefold()
    
    # Turkce stopwords
    stopwords = {'bir', 'bu', 've', 'ile', 'mi', 'mu', 'ne', 'nasil', 'nedir', 'hangi', 'kac', 'var', 'olan', 'icin'}
    
    # 3 harften uzun kelimeleri al, stopwordleri cikar
    keywords = [w for w in re.findall(r'\w+', query_lower) if len(w) > 3 and w not in stopwords]
    
    if not keywords:
        return []
    
    scored_sources = []
    for source in sources:
        content_lower = source.content.lower()
        title_lower = source.title.lower()
        
        score = 0
        for kw in keywords:
            if kw in title_lower:
                score += 3  # Baslikta gecen kelimeler daha onemli
            if kw in content_lower:
                score += 1
        
        if score > 0:
            scored_sources.append((score, source))
    
    # Skora gore sirala ve en iyi 3'u dondur
    scored_sources.sort(reverse=True, key=lambda x: x[0])
    relevant = [s[1] for s in scored_sources[:3]]
    
    # Hiç eşleşme yoksa ilk 2 kaynağı dondur
    return relevant


@login_required
def chat_page(request):
    """AI Asistan chat sayfasi"""
    sources = authorized_sources_for_user(request.user)
    context = {
        'sources': sources,
        'user_type': request.user.profile.user_type if hasattr(request.user, 'profile') else None,
    }
    return render(request, 'ai_assistant/chat.html', context)


@login_required
def chat_send(request):
    """Chat mesaj gonderme endpoint"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Sadece POST desteklenir.'})
    if is_rate_limited(request, scope='ai-chat', limit=20, window_seconds=60):
        return JsonResponse({'success': False, 'error': 'Çok fazla istek gönderildi. Lütfen kısa süre sonra tekrar deneyin.'}, status=429)

    try:
        data = json.loads(request.body)
        message = data.get('message', '').strip()

        if not message:
            return JsonResponse({'success': False, 'error': 'Mesaj bos olamaz.'})

        if len(message) > 2000:
            return JsonResponse({'success': False, 'error': 'Mesaj cok uzun (max 2000 karakter).'})

        # Aktif bilgi kaynaklarini al ve ilgili olanlari filtrele
        audience_key = audience_key_for_user(request.user)
        all_sources = authorized_sources_for_user(request.user)
        
        if not all_sources.exists():
            record_unanswered_question(message, audience_key)
            record_analytics_event(request, event_type='ai_answer', succeeded=False, metadata={'source_count': 0})
            return JsonResponse({
                'success': True,
                'response': 'Yetkiniz dahilindeki kaynaklarda bu soruyu yanıtlayacak bilgi bulunmuyor. Yöneticiden bilgi kaynağı eklemesini isteyebilirsiniz.',
                'sources_used': [],
                'cached': False
            })

        # Sadece ilgili kaynaklari sec
        sources = filter_relevant_sources(all_sources, message)

        if not sources:
            record_unanswered_question(message, audience_key)
            record_analytics_event(request, event_type='ai_answer', succeeded=False, metadata={'source_count': 0})
            return JsonResponse({
                'success': True,
                'response': 'Yetkiniz dahilindeki kaynaklarda bu soruyu yanıtlamak için yeterli bilgi bulunmuyor.',
                'sources_used': [],
                'cached': False,
            })

        # Gemini'den cevap al (cache kontrol dahil)
        result = get_gemini_response(message, sources, audience_key=audience_key)
        if not result.get('sources_used'):
            record_unanswered_question(message, audience_key)
        record_analytics_event(
            request,
            event_type='ai_answer',
            succeeded=bool(result.get('sources_used')),
            metadata={
                'source_count': len(result.get('sources_used') or []),
                'cached': bool(result.get('cached')),
            },
        )

        return JsonResponse({
            'success': True,
            'response': result['response'],
            'sources_used': result['sources_used'],
            'cached': result['cached']
        })

    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Gecersiz JSON.'})
    except Exception:
        logger.exception('AI sohbet isteği işlenemedi.')
        return JsonResponse({'success': False, 'error': 'İstek işlenirken bir hata oluştu.'}, status=500)


@login_required
def source_list(request):
    """Bilgi kaynaklarini listele"""
    if not can_manage_knowledge_sources(request.user):
        return render(request, 'dashboard/access_denied.html')

    sources = KnowledgeSource.objects.all()
    context = {
        'sources': sources,
    }
    return render(request, 'ai_assistant/source_list.html', context)


@login_required
@require_POST
def source_add(request):
    """Bilgi kaynagi ekle"""
    if not can_manage_knowledge_sources(request.user):
        return JsonResponse({'success': False, 'error': 'Yetkiniz yok.'})

    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Sadece POST desteklenir.'})

    try:
        title = request.POST.get('title', '').strip()
        description = request.POST.get('description', '').strip()
        content = request.POST.get('content', '').strip()
        category = request.POST.get('category', 'general')
        audience = request.POST.get('audience', 'all')
        source_file = request.FILES.get('source_file')

        if not title:
            return JsonResponse({'success': False, 'error': 'Baslik gerekli.'})

        valid_categories = {value for value, _ in KnowledgeSource.CATEGORY_CHOICES}
        if category not in valid_categories:
            return JsonResponse({'success': False, 'error': 'Geçersiz kategori.'}, status=400)

        valid_audiences = {value for value, _ in KnowledgeSource.AUDIENCE_CHOICES}
        if audience not in valid_audiences:
            return JsonResponse({'success': False, 'error': 'Geçersiz hedef kitle.'}, status=400)

        if source_file:
            if source_file.size > MAX_SOURCE_FILE_SIZE:
                return JsonResponse({'success': False, 'error': 'PDF en fazla 10 MB olabilir.'}, status=400)
            if not source_file.name.lower().endswith('.pdf'):
                return JsonResponse({'success': False, 'error': 'Yalnızca PDF dosyası yükleyebilirsiniz.'}, status=400)
            content_type = getattr(source_file, 'content_type', '')
            if content_type and content_type != 'application/pdf':
                return JsonResponse({'success': False, 'error': 'Geçersiz PDF dosyası.'}, status=400)
            position = source_file.tell()
            source_file.seek(0)
            signature = source_file.read(5)
            source_file.seek(position)
            if signature != b'%PDF-':
                return JsonResponse({'success': False, 'error': 'Dosya içeriği geçerli bir PDF değil.'}, status=400)
            try:
                pdf_text = extract_text_from_pdf(source_file)
            except (ValueError, PdfReadError):
                return JsonResponse({'success': False, 'error': 'PDF okunamadı veya metin içermiyor.'}, status=400)
            if content:
                content += "\n\n" + pdf_text
            else:
                content = pdf_text

        if not content:
            return JsonResponse({'success': False, 'error': 'Icerik veya dosya gerekli.'})

        source = KnowledgeSource.objects.create(
            title=title,
            description=description,
            content=content,
            category=category,
            audience=audience,
            source_file=source_file if source_file else None,
            created_by=request.user,
        )
        record_audit_event(actor=request.user, action='ai.knowledge_source_added', target=source, request=request)

        return JsonResponse({
            'success': True,
            'id': source.id,
            'message': f'"{source.title}" eklendi.'
        })

    except Exception:
        logger.exception('Bilgi kaynağı eklenemedi.')
        return JsonResponse({'success': False, 'error': 'Kaynak eklenirken bir hata oluştu.'}, status=500)


@login_required
@require_POST
def source_delete(request):
    """Bilgi kaynagi sil"""
    if not can_manage_knowledge_sources(request.user):
        return JsonResponse({'success': False, 'error': 'Yetkiniz yok.'})

    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Sadece POST desteklenir.'})

    try:
        data = json.loads(request.body)
        source_id = data.get('source_id')

        source = KnowledgeSource.objects.get(id=source_id)
        record_audit_event(actor=request.user, action='ai.knowledge_source_deleted', target=source, request=request)
        source.delete()

        return JsonResponse({'success': True, 'message': 'Silindi.'})

    except KnowledgeSource.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Kaynak bulunamadi.'})
    except Exception:
        logger.exception('Bilgi kaynağı silinemedi.')
        return JsonResponse({'success': False, 'error': 'Kaynak silinirken bir hata oluştu.'}, status=500)


@login_required
def source_update(request):
    """Bilgi kaynagi guncelle"""
    if not can_manage_knowledge_sources(request.user):
        return JsonResponse({'success': False, 'error': 'Yetkiniz yok.'})

    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Sadece POST desteklenir.'})

    try:
        data = json.loads(request.body)
        source_id = data.get('source_id')
        title = data.get('title', '').strip()
        description = data.get('description', '').strip()
        content = data.get('content', '').strip()
        category = data.get('category', 'general')
        audience = data.get('audience', 'all')
        is_active = data.get('is_active', True)

        if not source_id:
            return JsonResponse({'success': False, 'error': 'Kaynak ID gerekli.'})

        if not title:
            return JsonResponse({'success': False, 'error': 'Baslik gerekli.'})

        valid_categories = {value for value, _ in KnowledgeSource.CATEGORY_CHOICES}
        if category not in valid_categories:
            return JsonResponse({'success': False, 'error': 'Geçersiz kategori.'}, status=400)

        valid_audiences = {value for value, _ in KnowledgeSource.AUDIENCE_CHOICES}
        if audience not in valid_audiences:
            return JsonResponse({'success': False, 'error': 'Geçersiz hedef kitle.'}, status=400)

        source = KnowledgeSource.objects.get(id=source_id)
        source.title = title
        source.description = description
        source.content = content
        source.category = category
        source.audience = audience
        source.is_active = is_active
        source.save()

        return JsonResponse({
            'success': True,
            'message': f'"{source.title}" guncellendi.'
        })

    except KnowledgeSource.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Kaynak bulunamadi.'})
    except Exception:
        logger.exception('Bilgi kaynağı güncellenemedi.')
        return JsonResponse({'success': False, 'error': 'Kaynak güncellenirken bir hata oluştu.'}, status=500)


@login_required
def faq_stats(request):
    """FAQ istatistikleri sayfasi"""
    if not can_manage_knowledge_sources(request.user):
        return render(request, 'dashboard/access_denied.html')

    from .models import ChatCache, UnansweredQuestion
    
    caches = ChatCache.objects.all()
    total_cache = caches.count()
    total_hits = sum(c.hit_count for c in caches)
    most_asked = caches.order_by('-hit_count').first()
    unanswered = UnansweredQuestion.objects.filter(resolved_at__isnull=True)[:50]

    context = {
        'caches': caches,
        'total_cache': total_cache,
        'total_hits': total_hits,
        'most_asked': most_asked,
        'unanswered': unanswered,
    }
    return render(request, 'ai_assistant/faq_stats.html', context)


@login_required
def faq_delete(request):
    """FAQ cache sil"""
    if not can_manage_knowledge_sources(request.user):
        return JsonResponse({'success': False, 'error': 'Yetkiniz yok.'})

    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Sadece POST desteklenir.'})

    try:
        data = json.loads(request.body)
        cache_id = data.get('cache_id')

        from .models import ChatCache
        cache = ChatCache.objects.get(id=cache_id)
        cache.delete()

        return JsonResponse({'success': True, 'message': 'Cache silindi.'})

    except Exception:
        logger.exception('FAQ kaydı silinemedi.')
        return JsonResponse({'success': False, 'error': 'Kayıt silinirken bir hata oluştu.'}, status=500)


@login_required
def faq_clear_all(request):
    """Tum FAQ cache temizle"""
    if not can_manage_knowledge_sources(request.user):
        return JsonResponse({'success': False, 'error': 'Yetkiniz yok.'})

    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Sadece POST desteklenir.'})

    try:
        from .models import ChatCache
        count = ChatCache.objects.all().delete()[0]

        return JsonResponse({'success': True, 'message': f'{count} cache silindi.'})

    except Exception:
        logger.exception('FAQ önbelleği temizlenemedi.')
        return JsonResponse({'success': False, 'error': 'Önbellek temizlenirken bir hata oluştu.'}, status=500)
