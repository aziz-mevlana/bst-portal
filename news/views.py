from django.views.generic import ListView, DetailView
from .models import NewsItem

class NewsListView(ListView):
    model = NewsItem
    template_name = 'news/news_list.html'
    context_object_name = 'news_items'
    ordering = ['-date']
    paginate_by = 10

class NewsDetailView(DetailView):
    model = NewsItem
    template_name = 'news/news_detail.html'
    context_object_name = 'news_item' 