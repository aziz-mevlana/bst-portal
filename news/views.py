from django.shortcuts import render, get_object_or_404
from .models import Article
from django.shortcuts import redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages

def news_list(request):
    news = Article.objects.all()
    return render(request, 'news/news_list.html', {'news': news})

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
    return render(request, 'news/create_news.html')


