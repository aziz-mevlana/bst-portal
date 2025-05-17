from django.shortcuts import render
from django.views.generic import TemplateView
from events.models import Event
from news.models import NewsItem
from django.utils import timezone

class IndexView(TemplateView):
    template_name = 'index.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Son 3 etkinliği al
        context['events'] = Event.objects.filter(
            date__gte=timezone.now()
        ).order_by('date')[:3]
        
        # Son 3 haberi al
        context['news'] = NewsItem.objects.all().order_by('-date')[:3]
        
        return context 