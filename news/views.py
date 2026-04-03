from django.shortcuts import render, get_object_or_404
from .models import Article
from django.shortcuts import redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.template.loader import render_to_string

PAGE_SIZE = 12

def _user_can_manage_news(user, article=None):
    if not user.is_authenticated:
        return False
    profile = getattr(user, 'profile', None)
    user_type = getattr(profile, 'user_type', None)
    if user_type in ('staff_student', 'teacher'):
        return True
    if article and article.created_by_id == user.id:
        return True
    return False

def news_list(request):
    show_create_card = request.user.is_authenticated and hasattr(request.user, 'profile') and request.user.profile.user_type in ('staff_student', 'teacher')
    page_size = PAGE_SIZE - 1 if show_create_card else PAGE_SIZE
    news = Article.objects.all()[:page_size]
    total_count = Article.objects.count()
    has_more = total_count > page_size
    return render(request, 'news/news_list.html', {
        'news': news,
        'has_more': has_more,
        'next_offset': page_size,
        'total_count': total_count
    })

def news_load_more(request):
    offset = int(request.GET.get('offset', 0))
    limit = PAGE_SIZE
    
    news = Article.objects.all()[offset:offset + limit]
    total_count = Article.objects.count()
    has_more = offset + limit < total_count
    
    html = render_to_string('news/partials/news_item.html', {'news': news})
    
    return JsonResponse({
        'items': html,
        'has_more': has_more,
        'next_offset': offset + limit
    })

def news_detail(request, pk):
    try:
        news = Article.objects.get(pk=pk)
        return render(request, 'news/news_detail.html', {'news': news})
    except Article.DoesNotExist:
        messages.error(request, 'Haber bulunamadı.')
        return redirect('news:news_list')

@login_required
def create_news(request):
    if request.user.profile.user_type != 'staff_student' and request.user.profile.user_type != 'teacher':
        return redirect('news:news_list')

    if request.method == 'POST':
        title = request.POST.get('title')
        summary = request.POST.get('summary')
        content = request.POST.get('content')
        source = request.POST.get('source')
        url = request.POST.get('url')
        image = request.FILES.get('image')
        article_type = request.POST.get('article_type')
        article_category = request.POST.get('article_category')
        is_homepage = request.POST.get('is_homepage') == 'on'
        news = Article.objects.create(
            title=title,
            summary=summary,
            content=content,
            source=source,
            url=url,
            image=image,
            created_by=request.user,
            article_type=article_type,
            article_category=article_category,
            is_homepage=is_homepage
        )
        messages.success(request, 'Haber başarıyla oluşturuldu.')
        return redirect('news:news_list')
    return render(request, 'news/create_news.html', {
        'submit_label': 'Oluştur',
        'page_title': 'Yeni Haber Oluştur',
        'page_description': 'Yetkili kullanıcılar yeni haberleri buradan ekleyebilir.'
    })

@login_required
def edit_news(request, pk):
    article = get_object_or_404(Article, pk=pk)
    if not _user_can_manage_news(request.user, article):
        messages.error(request, 'Bu haberi düzenleme yetkiniz yok.')
        return redirect('news:news_detail', pk=pk)

    if request.method == 'POST':
        article.title = request.POST.get('title')
        article.summary = request.POST.get('summary')
        article.content = request.POST.get('content')
        article.source = request.POST.get('source')
        article.url = request.POST.get('url')
        article.article_type = request.POST.get('article_type')
        article.article_category = request.POST.get('article_category')
        article.is_homepage = request.POST.get('is_homepage') == 'on'
        image = request.FILES.get('image')
        if image:
            article.image = image
        article.save()
        messages.success(request, 'Haber başarıyla güncellendi.')
        return redirect('news:news_detail', pk=article.pk)

    return render(request, 'news/create_news.html', {
        'article': article,
        'submit_label': 'Güncelle',
        'page_title': 'Haberi Düzenle',
        'page_description': 'Haber içeriğini güncelleyin ve kaydedin.'
    })

@login_required
def delete_news(request, pk):
    article = get_object_or_404(Article, pk=pk)
    if not _user_can_manage_news(request.user, article):
        messages.error(request, 'Bu haberi silme yetkiniz yok.')
        return redirect('news:news_detail', pk=pk)

    if request.method == 'POST':
        article.delete()
        messages.success(request, 'Haber başarıyla silindi.')
        return redirect('news:news_list')

    return redirect('news:edit_news', pk=pk)
