from django.contrib.sitemaps import Sitemap
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from accounts.models import Profile
from career.models import Opportunity
from projects.models import Project
from news.models import Article


class ProjectSitemap(Sitemap):
    changefreq = 'weekly'
    priority = 0.8

    def items(self):
        return Project.objects.filter(
            visibility='public',
            approval_status='approved',
        ).exclude(slug='')

    def lastmod(self, item):
        return item.updated_at


class PortfolioSitemap(Sitemap):
    changefreq = 'weekly'
    priority = 0.7

    def items(self):
        return Profile.objects.filter(
            user_type__in={'student', 'staff_student'},
            user__is_active=True,
            user__is_staff=False,
            user__is_superuser=False,
            is_portfolio_public=True,
        ).exclude(public_slug='').select_related('user').order_by('pk')

    def lastmod(self, item):
        return item.updated_at


class StaticSitemap(Sitemap):
    changefreq = 'weekly'
    priority = 0.6

    def items(self):
        return [
            'portal:index',
            'projects:project_list',
            'portal:talent_list',
            'portal:academic_list',
            'events:event_list',
            'portal:privacy',
            'portal:kvkk_notice',
            'portal:terms',
            'career:opportunity_list',
            'news:news_list',
        ]

    def location(self, item):
        return reverse(item)


class OpportunitySitemap(Sitemap):
    changefreq = 'daily'
    priority = 0.7

    def items(self):
        return Opportunity.objects.filter(
            approval_status='approved',
            is_active=True,
        ).filter(Q(deadline__isnull=True) | Q(deadline__gte=timezone.localdate())).order_by('pk')

    def lastmod(self, item):
        return item.updated_at


class ArticleSitemap(Sitemap):
    changefreq = 'weekly'
    priority = 0.6

    def items(self):
        return Article.objects.public().exclude(slug='').order_by('pk')

    def lastmod(self, item):
        return item.date
