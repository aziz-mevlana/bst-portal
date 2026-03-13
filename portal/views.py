from django.shortcuts import render
from django.views.generic import TemplateView
from events.models import Event
from news.models import Article
from django.utils import timezone

class IndexView(TemplateView):
    template_name = 'index.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Son 3 etkinliği al - start_date kullanarak
        context['events'] = Event.objects.all().order_by('start_date')[:4]

        # Optimize: Only fetch news that should appear on homepage for slider, limited to 5 items
        # This is more efficient than fetching all news and filtering in template
        context['homepage_news'] = Article.objects.filter(
            is_homepage=True
        ).order_by('-date')
        
        # Fetch all news for the news section (not just homepage)
        context['all_news'] = Article.objects.all().order_by('-date')[:4]
        
        return context 