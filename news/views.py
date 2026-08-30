from django.shortcuts import render, get_object_or_404
from .models import Article
from django.shortcuts import redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, Http404
from django.core.paginator import Paginator
from django.db.models import Q
from django.template.loader import render_to_string
from django.views.decorators.http import require_POST
from accounts.policies import can_manage_news
from accounts.permissions import can_share_content
from .forms import ArticleForm

PAGE_SIZE = 12

def _user_can_manage_news(user, article=None):
    if can_manage_news(user):
        return True
    if not can_share_content(user) or getattr(user.profile, 'user_type', '') != 'approved_member':
        return False
    return article is None or article.created_by_id == user.pk

def news_list(request):
    show_create_card = _user_can_manage_news(request.user)
    page_size = PAGE_SIZE - 1 if show_create_card else PAGE_SIZE
    news = Article.objects.public()
    query = request.GET.get('q', '').strip()
    category = request.GET.get('category', '').strip()
    if query:
        news = news.filter(Q(title__icontains=query) | Q(summary__icontains=query) | Q(content__icontains=query))
    if category:
        news = news.filter(category=category)
    featured = news.filter(is_featured=True).first()
    if featured:
        news = news.exclude(pk=featured.pk)
    page = Paginator(news, page_size).get_page(request.GET.get('page'))
    total_count = news.count() + (1 if featured else 0)
    return render(request, 'news/news_list.html', {
        'news': page,
        'page_obj': page,
        'featured': featured,
        'total_count': total_count,
        'categories': Article.CATEGORY_CHOICES,
        'selected_category': category,
        'query': query,
        'can_manage_news': _user_can_manage_news(request.user),
    })

def news_load_more(request):
    try:
        offset = max(0, int(request.GET.get('offset', 0)))
    except (TypeError, ValueError):
        offset = 0
    limit = PAGE_SIZE

    news = Article.objects.public()[offset:offset + limit]
    total_count = Article.objects.public().count()
    has_more = offset + limit < total_count
    
    html = render_to_string('news/partials/news_item.html', {'news': news})
    
    return JsonResponse({
        'items': html,
        'has_more': has_more,
        'next_offset': offset + limit
    })

def news_detail(request, pk):
    news = Article.objects.filter(pk=pk).first()
    if news is None or (not news.is_approved and not _user_can_manage_news(request.user, news)):
        messages.error(request, 'Haber bulunamadı.')
        return redirect('news:news_list')
    return _render_news_detail(request, news)


def news_detail_slug(request, slug):
    news = Article.objects.filter(slug=slug).first()
    if news is None or (not news.is_approved and not _user_can_manage_news(request.user, news)):
        raise Http404
    return _render_news_detail(request, news)


def _render_news_detail(request, news):
    related = Article.objects.public().exclude(pk=news.pk)
    if news.category:
        related = related.filter(category=news.category)
    return render(request, 'news/news_detail.html', {
        'news': news,
        'related_news': related[:3],
        'meta_title': f'{news.title} | BST Haberler',
        'meta_description': (news.summary or news.content)[:160],
        'canonical_url': request.build_absolute_uri(news.get_absolute_url()),
        'meta_robots': 'index,follow' if news.is_approved else 'noindex,nofollow',
        'can_manage_news': _user_can_manage_news(request.user, news),
    })

@login_required
def create_news(request):
    if not _user_can_manage_news(request.user):
        return redirect('news:news_list')

    if request.method == 'POST':
        form = ArticleForm(request.POST, request.FILES)
        if form.is_valid():
            news = form.save(commit=False)
            news.created_by = request.user
            news.is_approved = bool(request.user.is_staff or request.user.is_superuser)
            news.save()
            messages.success(request, 'Haber yayımlandı.' if news.is_approved else 'Haber yönetici onayına gönderildi.')
            return redirect('news:news_list')
        messages.error(request, 'Haber kaydedilemedi. Lütfen işaretli alanları kontrol edin.')
    else:
        form = ArticleForm()
    return render(request, 'news/create_news.html', {
        'article': form.instance,
        'form': form,
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
        form = ArticleForm(request.POST, request.FILES, instance=article)
        if form.is_valid():
            article = form.save(commit=False)
            requires_review = not (request.user.is_staff or request.user.is_superuser)
            if requires_review:
                article.is_approved = False
                article.is_homepage = False
                article.is_featured = False
            article.save()
            form.save_m2m()
            messages.success(
                request,
                'Haber güncellendi ve yeniden yönetici onayına gönderildi.'
                if requires_review else 'Haber başarıyla güncellendi.',
            )
            return redirect('news:news_detail', pk=article.pk)
        messages.error(request, 'Haber güncellenemedi. Lütfen işaretli alanları kontrol edin.')
    else:
        form = ArticleForm(instance=article)

    return render(request, 'news/create_news.html', {
        'article': article,
        'form': form,
        'submit_label': 'Güncelle',
        'page_title': 'Haberi Düzenle',
        'page_description': 'Haber içeriğini güncelleyin ve kaydedin.'
    })

@login_required
@require_POST
def delete_news(request, pk):
    article = get_object_or_404(Article, pk=pk)
    if not _user_can_manage_news(request.user, article):
        messages.error(request, 'Bu haberi silme yetkiniz yok.')
        return redirect('news:news_detail', pk=pk)

    article.delete()
    messages.success(request, 'Haber başarıyla silindi.')
    return redirect('news:news_list')
