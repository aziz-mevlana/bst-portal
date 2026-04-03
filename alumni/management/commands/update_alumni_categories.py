import os
import re
from django.core.management.base import BaseCommand
from alumni.models import Alumni
from projects.models import ProjectCategory, Technology


POSITION_CATEGORY_MAP = {
    'data scientist': 'Data Science',
    'data analyst': 'Data Science',
    'veri bilimci': 'Data Science',
    'veri analist': 'Data Science',
    'machine learning': 'Data Science',
    'ml engineer': 'Data Science',
    'yapay zeka': 'Data Science',
    'ai engineer': 'Data Science',
    'deep learning': 'Data Science',
    
    'blockchain': 'Blockchain',
    'blockchain developer': 'Blockchain',
    'crypto': 'Blockchain',
    
    'mobile': 'Mobil Uygulama',
    'ios': 'Mobil Uygulama',
    'android': 'Mobil Uygulama',
    'flutter': 'Mobil Uygulama',
    'react native': 'Mobil Uygulama',
    'swift': 'Mobil Uygulama',
    'kotlin': 'Mobil Uygulama',
    'mobil': 'Mobil Uygulama',
    
    'web': 'Web Geliştirme',
    'frontend': 'Web Geliştirme',
    'backend': 'Web Geliştirme',
    'full stack': 'Web Geliştirme',
    'full-stack': 'Web Geliştirme',
    'web developer': 'Web Geliştirme',
    
    'game': 'Oyun Geliştirme',
    'oyun': 'Oyun Geliştirme',
    'unity': 'Oyun Geliştirme',
    'unreal': 'Oyun Geliştirme',
    
    'cyber': 'Siber Güvenlik',
    'security': 'Siber Güvenlik',
    'güvenlik': 'Siber Güvenlik',
    'penetration': 'Siber Güvenlik',
    
    'iot': 'IoT',
    'gömülü': 'Gömülü Sistem',
    'embedded': 'Gömülü Sistem',
    'firmware': 'Gömülü Sistem',
    'arduino': 'Gömülü Sistem',
    'raspberry': 'Gömülü Sistem',
    
    'desktop': 'Masaüstü Uygulama',
    'masaüstü': 'Masaüstü Uygulama',
    'desktop app': 'Masaüstü Uygulama',
}

POSITION_TECH_MAP = {
    'python': 'Python',
    'java': 'Java',
    'javascript': 'JavaScript',
    'js': 'JavaScript',
    'typescript': 'TypeScript',
    'react': 'React',
    'angular': 'Angular',
    'vue': 'Vue.js',
    'vue.js': 'Vue.js',
    'node': 'Node.js',
    'node.js': 'Node.js',
    'django': 'Django',
    'flask': 'Flask',
    'flutter': 'Flutter',
    'swift': 'Swift',
    'kotlin': 'Kotlin',
    'c++': 'C++',
    'c#': 'C#',
    '.net': '.NET',
    'sql': 'SQL',
    'mysql': 'MySQL',
    'postgresql': 'PostgreSQL',
    'mongodb': 'MongoDB',
    'docker': 'Docker',
    'kubernetes': 'Kubernetes',
    'aws': 'AWS',
    'azure': 'Azure',
    'git': 'Git',
    'html': 'HTML/CSS',
    'css': 'HTML/CSS',
    'tensorflow': 'TensorFlow',
    'pytorch': 'PyTorch',
    'keras': 'Keras',
    'pandas': 'Pandas',
    'numpy': 'NumPy',
    'flutter': 'Flutter',
    'react native': 'React Native',
}


class Command(BaseCommand):
    help = 'Mezunların pozisyonlarına göre kategorilerini ve teknolojilerini günceller'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Değişiklik yapma, sadece ne olacağını göster',
        )

    def handle(self, *args, **options):
        dry_run = options.get('dry_run', False)
        
        # Get or create categories by name
        existing_cats = {c.name.lower(): c for c in ProjectCategory.objects.all()}
        print(f'Mevcut kategoriler: {list(existing_cats.keys())}')
        
        # Get or create technologies by name
        existing_techs = {t.name.lower(): t for t in Technology.objects.all()}
        print(f'Mevcut teknolojiler: {list(existing_techs.keys())}')
        
        alumni_list = Alumni.objects.all()
        updated_count = 0
        
        for alumni in alumni_list:
            position = (alumni.current_position or '').lower()
            company = (alumni.company or '').lower()
            
            # Find matching categories (avoid duplicates)
            matched_cats = []
            seen_cat_names = set()
            for keyword, cat_name in POSITION_CATEGORY_MAP.items():
                if keyword in position or keyword in company:
                    if cat_name.lower() in existing_cats and cat_name.lower() not in seen_cat_names:
                        matched_cats.append(existing_cats[cat_name.lower()])
                        seen_cat_names.add(cat_name.lower())
            
            # Find matching technologies
            matched_techs = []
            for keyword, tech_name in POSITION_TECH_MAP.items():
                if keyword in position or keyword in company:
                    if tech_name.lower() in existing_techs:
                        matched_techs.append(existing_techs[tech_name.lower()])
            
            if matched_cats or matched_techs:
                if not dry_run:
                    alumni.categories.set(matched_cats)
                    alumni.technologies.set(matched_techs)
                    alumni.save()
                
                print(f'{alumni.get_display_name}:')
                print(f'  Position: {alumni.current_position}')
                print(f'  Categories: {[c.name for c in matched_cats]}')
                print(f'  Technologies: {[t.name for t in matched_techs]}')
                updated_count += 1
        
        self.stdout.write(self.style.SUCCESS(
            f'İşlem tamamlandı: {updated_count} mezun güncellendi.'
        ))