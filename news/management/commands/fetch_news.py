import feedparser
import requests
from django.core.management.base import BaseCommand
from django.utils.text import slugify
from news.models import Article # Uygulama adınıza göre bu import'u güncelleyin

feedparser.USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

class Command(BaseCommand):
    help = 'RSS kaynaklarından haberleri çek veya demo veri ekle'

    def add_arguments(self, parser):
        parser.add_argument('--demo', action='store_true', help='Demo haberler ekle')
        parser.add_argument('--approve', action='store_true', help='Otomatik onayla')

    def handle(self, *args, **options):
        if options.get('demo'):
            self._add_demo_news()
            return

        self.stdout.write(self.style.WARNING('RSS Haber çekme işlemi başlıyor...'))
        
        total = 0
        total += self._fetch_from_webrazzi()
        total += self._fetch_from_shift()
        total += self._fetch_from_webtekno()

        self.stdout.write(self.style.SUCCESS(f'\nİşlem tamamlandı! Toplam {total} yeni haber çekildi.'))

    def _fetch_rss(self, url, category, source_name):
        try:
            # Tarayıcı kimliğini artık requests üzerinden gönderiyoruz
            headers = {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
            
            # Bağlantıyı requests ile yap (Timeout ekleyerek sonsuza kadar beklemesini önlüyoruz)
            response = requests.get(url, headers=headers, timeout=10)
            
            # Gelen XML verisini feedparser'a okutuyoruz
            feed = feedparser.parse(response.content)
            
            # Hala bozo (hata) veriyorsa gerçek hatayı ekrana yazdır
            if feed.bozo:
                self.stdout.write(self.style.WARNING(f"  -> UYARI: {source_name} ayrıştırılamadı. Hata: {feed.bozo_exception}"))
                return 0

            if not feed.entries:
                self.stdout.write(self.style.WARNING(f"  -> UYARI: {source_name} feed'i boş geldi. (HTTP: {response.status_code})"))
                return 0

            count = 0
            for entry in feed.entries[:10]: 
                # Benzersiz URL kontrolü
                if not Article.objects.filter(source_url=entry.link).exists():
                    
                    description_text = entry.get('description', '')
                    content_text = entry.get('content_encoded', entry.get('summary', description_text))
                    if hasattr(entry, 'content') and entry.content:
                        content_text = entry.content[0].value
                    image_url = ""
                    if hasattr(entry, 'media_content') and entry.media_content:
                        image_url = entry.media_content[0].get('url', '')
                    elif hasattr(entry, 'media_thumbnail') and entry.media_thumbnail:
                        image_url = entry.media_thumbnail[0].get('url', '')
                    elif 'links' in entry:
                        for link in entry.links:
                            if 'image' in link.get('type', ''):
                                image_url = link.get('href', '')
                                break

                    slug_str = slugify(entry.title)

                    Article.objects.create(
                        title=entry.title,
                        summary=description_text[:500] if description_text else content_text[:500],
                        content=content_text,
                        source=source_name,
                        url=entry.link,
                        source_url=entry.link,
                        category=category,
                        image_url=image_url,
                        is_approved=False,
                        article_type='news'
                    )
                    count += 1
            
            self.stdout.write(self.style.SUCCESS(f'- {source_name}: {count} yeni haber kaydedildi.'))
            return count

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'- {source_name} hatası: {str(e)}'))
            return 0

    def _fetch_from_webrazzi(self):
        self.stdout.write('Webrazzi taranıyor...')
        return self._fetch_rss('https://webrazzi.com/feed/', 'technology', 'Webrazzi')

    def _fetch_from_shift(self):
        self.stdout.write('ShiftDelete taranıyor...')
        return self._fetch_rss('https://shiftdelete.net/feed', 'technology', 'ShiftDelete')

    def _fetch_from_webtekno(self):
        self.stdout.write('Webtekno taranıyor...')
        return self._fetch_rss('https://www.webtekno.com/rss.xml', 'technology', 'Webtekno')

    def _add_demo_news(self):
        demo_news = [
            {
                'title': 'Yapay Zeka: 2026 yılında neler değişti?',
                'summary': 'Yapay zeka alanında bu yıl büyük gelismeler yasandi. Buyuk dil modelleri ve generatif AI tesadufi yazilim gelistirme sürecini tamamen degistirdi.',
                'source': 'TechDemo',
                'category': 'technology',
                'url': 'https://example.com/ai-2026'
            },
            {
                'title': 'Python en populer programlama dili oldu',
                'summary': 'TIOBE indeksine gore Python, Java ve C++ yi geride birakarak en cok kullanilan programlama dili oldu.',
                'source': 'TechDemo',
                'category': 'software',
                'url': 'https://example.com/python-populer'
            },
            {
                'title': 'Universite ögrencileri için yeni burs programlari',
                'summary': 'Turkiye deki universiteler, teknoloji alaninda ogrenim goren ogrenciler için yeni burs programlari baslatti.',
                'source': 'UniDemo',
                'category': 'university',
                'url': 'https://example.com/burs-2026'
            },
            {
                'title': 'Turk yazilim sektörü buyumeye devam ediyor',
                'summary': 'Yerli yazilim sirketlerinin ihracati geçen yila göre %35 artti. Sektor, 2026 hedeflerini tutturdu.',
                'source': 'SectorDemo',
                'category': 'sector',
                'url': 'https://example.com/sektor-buyume'
            },
            {
                'title': 'Google, yeni nesil bulut servislerini açıkladı',
                'summary': 'Google Cloud, yapay zeka destekli yeni hizmetlerini tanıttı. Kurumlar artık kendi verileri uzerinde AI modelleri egitabilecek.',
                'source': 'TechDemo',
                'category': 'technology',
                'url': 'https://example.com/google-cloud'
            },
            {
                'title': 'MIT ve Stanford: Yeni online kurslar ücretsiz',
                'summary': 'Dunyanın onemli universiteleri, online egitim platformlarinda yeni programlar baslatti. Turk ogrenciler de katilabilir.',
                'source': 'UniDemo',
                'category': 'university',
                'url': 'https://example.com/online-kurs'
            },
        ]

        count = 0
        for news in demo_news:
            if not Article.objects.filter(source_url=news['url']).exists():
                Article.objects.create(
                    title=news['title'],
                    summary=news['summary'],
                    content=news['summary'],
                    source=news['source'],
                    url=news['url'],
                    source_url=news['url'],
                    category=news['category'],
                    is_approved=False,
                    article_type='ai'
                )
                count += 1

        self.stdout.write(self.style.SUCCESS(f'{count} yeni demo haber eklendi.'))