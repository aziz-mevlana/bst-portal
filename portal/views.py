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
        context['events'] = Event.objects.all().order_by('start_date')[:3]

        # Article modelini kullan - son 3 haberi al
        context['news'] = Article.objects.all().order_by('-date')[:3]
        return context 