from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import Event, News

def index(request):
    events = Event.objects.filter(is_active=True)[:3]
    news = News.objects.filter(is_published=True)[:3]
    return render(request, 'index.html', {'events': events, 'news': news})

def event_list(request):
    events = Event.objects.filter(is_active=True)
    return render(request, 'events/event_list.html', {'events': events})

def event_detail(request, event_id):
    event = get_object_or_404(Event, id=event_id, is_active=True)
    return render(request, 'events/event_detail.html', {'event': event})

def news_list(request):
    news = News.objects.filter(is_published=True)
    return render(request, 'events/news_list.html', {'news': news})

def news_detail(request, news_id):
    news = get_object_or_404(News, id=news_id, is_published=True)
    return render(request, 'events/news_detail.html', {'news': news})

@login_required
def create_event(request):
    if request.method == 'POST':
        # Event oluşturma işlemleri burada yapılacak
        pass
    return render(request, 'events/create_event.html')

@login_required
def create_news(request):
    if request.method == 'POST':
        # Haber oluşturma işlemleri burada yapılacak
        pass
    return render(request, 'events/create_news.html')
