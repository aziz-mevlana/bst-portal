from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from projects.models import Project, ProjectRequest, ProjectCategory, Technology
from events.models import Event
from news.models import Article
from datetime import datetime, timedelta
import random


class Command(BaseCommand):
    help = 'Populates the database with test data'

    def handle(self, *args, **options):
        # Get or create a test user
        user, created = User.objects.get_or_create(
            username='testuser',
            defaults={
                'first_name': 'Test',
                'last_name': 'User',
                'email': 'test@example.com'
            }
        )
        if created:
            user.set_password('testpass123')
            user.save()
            self.stdout.write(self.style.SUCCESS(f'Created user: {user.username}'))

        # Create categories
        categories_data = [
            ('Web Geliştirme', '#3B82F6'),
            ('Mobil Uygulama', '#10B981'),
            ('Yapay Zeka', '#8B5CF6'),
            ('Veri Bilimi', '#F59E0B'),
            ('Siber Güvenlik', '#EF4444'),
            ('Oyun Geliştirme', '#EC4899'),
            ('Blockchain', '#06B6D4'),
            ('IoT', '#84CC16'),
        ]
        categories = []
        for name, color in categories_data:
            cat, _ = ProjectCategory.objects.get_or_create(name=name, defaults={'color': color})
            categories.append(cat)

        # Create technologies
        techs_data = [
            ('Python', '#3776AB'),
            ('JavaScript', '#F7DF1E'),
            ('React', '#61DAFB'),
            ('Django', '#092E20'),
            ('Flutter', '#02569B'),
            ('TensorFlow', '#FF6F00'),
            ('Node.js', '#339933'),
            ('SQL', '#4479A1'),
        ]
        technologies = []
        for name, color in techs_data:
            tech, _ = Technology.objects.get_or_create(name=name, defaults={'color': color})
            technologies.append(tech)

        # Create 30 projects
        project_titles = [
            'Öğrenci Yönetim Sistemi', 'E-ticaret Platformu', 'Sosyal Medya Uygulaması',
            'Blog Sitesi', 'Finans Takip Uygulaması', 'Sağlık Bilgi Sistemi',
            'Kütüphane Otomasyonu', 'Online Sınav Platformu', 'Chat Uygulaması',
            'Video Konferans Sistemi', 'Hava Durumu Uygulaması', 'Yemek Sipariş Platformu',
            'Seyahat Planlama Uygulaması', 'Müzik Player', 'Fotoğraf Galerisi',
            'Kurumsal Web Sitesi', 'E-devlet Entegrasyonu', 'Akıllı Ev Sistemi',
            'QR Kod Okuyucu', 'Sesli Asistan', 'Chatbot Sistemi',
            'Veri Görselleştirme', 'Kargo Takip Sistemi', 'İş Bulma Platformu',
            'Online Kitap Okuma', 'Fitness Takip',             'Bütçe Yönetimi',
            'Hatırlatıcı Uygulama', 'Not Alma App', 'Anket Uygulaması'
        ]

        for i, title in enumerate(project_titles):
            # Create project request first
            project_req, _ = ProjectRequest.objects.get_or_create(
                title=f'{title} - Request',
                defaults={
                    'course': 'Bilgisayar Mühendisliği',
                    'duration': '4 ay',
                    'team_size': 4,
                    'teacher': user
                }
            )
            
            project, created = Project.objects.get_or_create(
                title=title,
                defaults={
                    'project_request': project_req,
                    'description': f'{title} projesi, modern teknolojiler kullanılarak geliştirilmiş kapsamlı bir uygulamadır. '
                                   f'Kullanıcı dostu arayüzü ve güçlü altyapısı ile öne çıkmaktadır. '
                                   f'Bu proje, gerçek dünya problemlerini çözmek için tasarlanmıştır.',
                    'created_by': user,
                    'status': random.choice(['draft', 'completed']),
                    'advisor': user
                }
            )
            
            if created:
                # Add random categories and technologies
                project.categories.set(random.sample(categories, random.randint(1, 3)))
                project.technologies.set(random.sample(technologies, random.randint(2, 5)))

        self.stdout.write(self.style.SUCCESS(f'Created {len(project_titles)} projects'))

        # Create 30 events
        event_titles = [
            'Python Workshop', 'Web Geliştirme Semineri', 'AI Konferansı',
            'Flutter Eğitimi', 'Cyber Security Summit', 'Data Science Bootcamp',
            'React Native Workshop', 'Blockchain Teknolojileri', 'IoT Projesi Tanıtımı',
            'UX/UI Tasarım Eğitimi', 'Cloud Computing Semineri', 'Mobile Dev Day',
            'DevOps Konferansı', 'Machine Learning Atölyesi', 'Full Stack Geliştirme',
            'Open Source Summit', 'Tech Career Fair', 'Startup Pitching',
            'Hackathon 2024', 'Code Review Workshop', 'API Development',
            'Database Optimization', 'Microservices Architecture', 'Agile Methodology',
            'Testing & QA Workshop', 'Performance Tuning', 'Security Best Practices',
            'Cloud Native Development', 'Containerization with Docker', 'Kubernetes Training'
        ]

        event_types = ['seminar', 'workshop', 'conference', 'social', 'other']
        locations = ['A101', 'B202', 'C303', 'Konferans Salonu', 'Amfi 1', 'Amfi 2', 'Online']

        for i, title in enumerate(event_titles):
            start_date = datetime.now() + timedelta(days=i)
            end_date = start_date + timedelta(hours=2)
            
            event, created = Event.objects.get_or_create(
                title=title,
                defaults={
                    'description': f'{title} etkinliği, alanında uzman eğitmenler tarafından gerçekleştirilecektir. '
                                   f'Katılımcılar teorik bilgi ve pratik uygulama fırsatı bulacaktır. '
                                   f'Tüm öğrencilerimiz davetlidir.',
                    'event_type': random.choice(event_types),
                    'location': random.choice(locations),
                    'start_date': start_date,
                    'end_date': end_date,
                    'created_by': user
                }
            )

        self.stdout.write(self.style.SUCCESS(f'Created {len(event_titles)} events'))

        # Create 30 news/articles
        news_titles = [
            'Yeni Yazılım Duyurusu', 'Öğrenci Başarısı', 'Tech Summit 2024',
            'Yeni Laboratuvar Açılışı', 'Sektör İşbirliği', 'Ödül Kazanımı',
            'Staj İlanları', 'Konferans Katılımı', 'Proje Tanıtımı',
            'Yeni Dönem Duyurusu', 'Kurum Ziyareti', 'Workshop Düzenlendi',
            'Mezunlar Buluşması', 'Tech Awards 2024', 'İnovasyon Haftası',
            'Yeni Ortaklık', 'Hackathon Sonuçları', 'Başarı Hikayesi',
            'Yeni Kurs Açılışı', 'Sertifika Programı', 'Mentorluk Programı',
            'Career Day Duyurusu', 'Yeni Teknoloji Haberleri', 'Yazılım Güncellemesi',
            'Etkinlik Takvimi', 'Konuk Konuşmacı', 'Proje Sergisi',
            'Online Eğitim Duyurusu', 'Yeni Araştırma Projesi', 'Yıl Sonu Etkinliği'
        ]

        sources = ['BST Portal', 'Teknoloji Haberleri', 'Bilim Dünyası', 'Tech News', 'Güncel Akademi']

        for i, title in enumerate(news_titles):
            article, created = Article.objects.get_or_create(
                title=title,
                defaults={
                    'summary': f'{title} hakkında güncel bilgiler ve detaylar.',
                    'content': f'{title} ile ilgili detaylı bilgiler aşağıda yer almaktadır. '
                               f'Bu haber, en güncel bilgiler ışığında hazırlanmıştır. '
                               f'Konu ile ilgili gelişmeleri takip etmeye devam edin.',
                    'source': random.choice(sources),
                    'created_by': user,
                    'date': datetime.now() - timedelta(days=i)
                }
            )

        self.stdout.write(self.style.SUCCESS(f'Created {len(news_titles)} news articles'))
        self.stdout.write(self.style.SUCCESS('Test data population completed!'))
