from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import Event

def index(request):
    events = Event.objects.filter(is_active=True)[:3]
    return render(request, 'index.html', {'events': events})

def event_list(request):
    events = Event.objects.filter(is_active=True)
    return render(request, 'events/event_list.html', {'events': events})

def event_detail(request, event_id):
    event = get_object_or_404(Event, id=event_id, is_active=True)
    return render(request, 'events/event_detail.html', {'event': event})

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
