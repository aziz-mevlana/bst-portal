from django.shortcuts import render, get_object_or_404
from .models import News
from django.shortcuts import redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages

def news_list(request):
    news = News.objects.all()
    return render(request, 'news/news_list.html', {'news': news})

def news_detail(request, pk):
    news = get_object_or_404(News, pk=pk)
    return render(request, 'news/news_detail.html', {'news': news})

@login_required
def create_news(request):
    if request.method == 'POST':
        title = request.POST.get('title')
        summary = request.POST.get('summary')
        content = request.POST.get('content')
        source = request.POST.get('source')
        url = request.POST.get('url')
        image = request.FILES.get('image')
        news_type = request.POST.get('news_type')
        news_category = request.POST.get('news_category')
        news = News.objects.create(
            title=title,
            summary=summary,
            content=content,
            source=source,
            url=url,
            image=image,
            created_by=request.user,
            news_type=news_type,
            news_category=news_category
        )
        messages.success(request, 'Haber başarıyla oluşturuldu.')
        return redirect('news:news_list')
    return render(request, 'news/create_news.html')


