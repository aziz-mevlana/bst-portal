from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from .models import KnowledgeSource
from .gemini_service import get_gemini_response
from .pdf_utils import extract_text_from_pdf
import json


def is_teacher_or_staff(user):
    if not user.is_authenticated:
        return False
    if not hasattr(user, 'profile'):
        return False
    return user.profile.user_type in ['teacher', 'staff_student']


def filter_relevant_sources(sources, query):
    """Soruya gore ilgili kaynaklari filtrele"""
    query_lower = query.lower()
    
    # Turkce stopwords
    stopwords = {'bir', 'bu', 've', 'ile', 'mi', 'mu', 'ne', 'nasil', 'nedir', 'hangi', 'kac', 'var', 'olan', 'icin'}
    
    # 3 harften uzun kelimeleri al, stopwordleri cikar
    keywords = [w for w in query_lower.split() if len(w) > 3 and w not in stopwords]
    
    if not keywords:
        return list(sources[:3])  # Keyword yoksa ilk 3 kaynagi dondur
    
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
    return relevant if relevant else list(sources[:2])


@login_required
def chat_page(request):
    """AI Asistan chat sayfasi"""
    sources = KnowledgeSource.objects.filter(is_active=True)
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

    try:
        data = json.loads(request.body)
        message = data.get('message', '').strip()

        if not message:
            return JsonResponse({'success': False, 'error': 'Mesaj bos olamaz.'})

        if len(message) > 2000:
            return JsonResponse({'success': False, 'error': 'Mesaj cok uzun (max 2000 karakter).'})

        # Aktif bilgi kaynaklarini al ve ilgili olanlari filtrele
        all_sources = KnowledgeSource.objects.filter(is_active=True)
        
        if not all_sources.exists():
            return JsonResponse({
                'success': True,
                'response': 'Henuz bilgi kaynagi eklenmemis. Yonetici panelinden bilgi kaynagi eklenmesini talep edin.',
                'cached': False
            })

        # Sadece ilgili kaynaklari sec
        sources = filter_relevant_sources(all_sources, message)

        # Gemini'den cevap al (cache kontrol dahil)
        result = get_gemini_response(message, sources)

        return JsonResponse({
            'success': True,
            'response': result['response'],
            'sources_used': result['sources_used'],
            'cached': result['cached']
        })

    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Gecersiz JSON.'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
def source_list(request):
    """Bilgi kaynaklarini listele"""
    if not is_teacher_or_staff(request.user):
        return render(request, 'dashboard/access_denied.html')

    sources = KnowledgeSource.objects.all()
    context = {
        'sources': sources,
    }
    return render(request, 'ai_assistant/source_list.html', context)


@login_required
def source_add(request):
    """Bilgi kaynagi ekle"""
    if not is_teacher_or_staff(request.user):
        return JsonResponse({'success': False, 'error': 'Yetkiniz yok.'})

    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Sadece POST desteklenir.'})

    try:
        title = request.POST.get('title', '').strip()
        description = request.POST.get('description', '').strip()
        content = request.POST.get('content', '').strip()
        category = request.POST.get('category', 'general')
        source_file = request.FILES.get('source_file')

        if not title:
            return JsonResponse({'success': False, 'error': 'Baslik gerekli.'})

        # PDF dosyasi yuklenmisse metin cikar
        if source_file and source_file.name.endswith('.pdf'):
            pdf_text = extract_text_from_pdf(source_file)
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
            source_file=source_file if source_file else None,
            created_by=request.user,
        )

        return JsonResponse({
            'success': True,
            'id': source.id,
            'message': f'"{source.title}" eklendi.'
        })

    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
def source_delete(request):
    """Bilgi kaynagi sil"""
    if not is_teacher_or_staff(request.user):
        return JsonResponse({'success': False, 'error': 'Yetkiniz yok.'})

    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Sadece POST desteklenir.'})

    try:
        data = json.loads(request.body)
        source_id = data.get('source_id')

        source = KnowledgeSource.objects.get(id=source_id)
        source.delete()

        return JsonResponse({'success': True, 'message': 'Silindi.'})

    except KnowledgeSource.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Kaynak bulunamadi.'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
def source_update(request):
    """Bilgi kaynagi guncelle"""
    if not is_teacher_or_staff(request.user):
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
        is_active = data.get('is_active', True)

        if not source_id:
            return JsonResponse({'success': False, 'error': 'Kaynak ID gerekli.'})

        if not title:
            return JsonResponse({'success': False, 'error': 'Baslik gerekli.'})

        source = KnowledgeSource.objects.get(id=source_id)
        source.title = title
        source.description = description
        source.content = content
        source.category = category
        source.is_active = is_active
        source.save()

        return JsonResponse({
            'success': True,
            'message': f'"{source.title}" guncellendi.'
        })

    except KnowledgeSource.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Kaynak bulunamadi.'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
def faq_stats(request):
    """FAQ istatistikleri sayfasi"""
    if not is_teacher_or_staff(request.user):
        return render(request, 'dashboard/access_denied.html')

    from .models import ChatCache
    
    caches = ChatCache.objects.all()
    total_cache = caches.count()
    total_hits = sum(c.hit_count for c in caches)
    most_asked = caches.order_by('-hit_count').first()

    context = {
        'caches': caches,
        'total_cache': total_cache,
        'total_hits': total_hits,
        'most_asked': most_asked,
    }
    return render(request, 'ai_assistant/faq_stats.html', context)


@login_required
def faq_delete(request):
    """FAQ cache sil"""
    if not is_teacher_or_staff(request.user):
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

    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
def faq_clear_all(request):
    """Tum FAQ cache temizle"""
    if not is_teacher_or_staff(request.user):
        return JsonResponse({'success': False, 'error': 'Yetkiniz yok.'})

    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Sadece POST desteklenir.'})

    try:
        from .models import ChatCache
        count = ChatCache.objects.all().delete()[0]

        return JsonResponse({'success': True, 'message': f'{count} cache silindi.'})

    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})
