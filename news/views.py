from django.shortcuts import render, get_object_or_404
from .models import News

def index(request):
    news = News.objects.all()[:3]
    return render(request, 'index.html', {'news': news})

def news_list(request):
    news = News.objects.all()
    return render(request, 'news/news_list.html', {'news': news})

def news_detail(request, pk):
    news = get_object_or_404(News, pk=pk)
    return render(request, 'news/news_detail.html', {'news': news})

