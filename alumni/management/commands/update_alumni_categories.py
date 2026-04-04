import os
import re
import sqlite3
from django.core.management.base import BaseCommand
from alumni.models import Alumni, WorkExperience
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
    'data engineer': 'Data Science',
    'veri mühendisi': 'Data Science',
    
    'blockchain': 'Blockchain',
    'blockchain developer': 'Blockchain',
    'crypto': 'Blockchain',
    'solidity': 'Blockchain',
    
    'mobile': 'Mobil',
    'ios': 'Mobil',
    'android': 'Mobil',
    'flutter': 'Mobil',
    'react native': 'Mobil',
    'swift': 'Mobil',
    'kotlin': 'Mobil',
    'mobil': 'Mobil',
    'mobile developer': 'Mobil',
    'Mobil': 'Mobil',
    
    'web': 'Web',
    'frontend': 'Web',
    'backend': 'Web',
    'full stack': 'Web',
    'full-stack': 'Web',
    'web developer': 'Web',
    'fullstack': 'Web',
    'front end': 'Web',
    'back end': 'Web',
    
    'game': 'Oyun',
    'oyun': 'Oyun',
    'unity': 'Oyun',
    'unreal': 'Oyun',
    'game developer': 'Oyun',
    'oyun geliştirici': 'Oyun',
    
    'cyber': 'Siber Güvenlik',
    'security': 'Siber Güvenlik',
    'güvenlik': 'Siber Güvenlik',
    'penetration': 'Siber Güvenlik',
    'siber': 'Siber Güvenlik',
    
    'iot': 'IoT',
    'gömülü': 'Gömülü Sistem',
    'embedded': 'Gömülü Sistem',
    'firmware': 'Gömülü Sistem',
    'arduino': 'Gömülü Sistem',
    'raspberry': 'Gömülü Sistem',
    'embedded systems': 'Gömülü Sistem',
    
    'desktop': 'Masaüstü Uygulama',
    'masaüstü': 'Masaüstü Uygulama',
    'desktop app': 'Masaüstü Uygulama',
    'desktop developer': 'Masaüstü Uygulama',
    'windows': 'Masaüstü Uygulama',
    
    'devops': 'DevOps',
    'sre': 'DevOps',
    'ci/cd': 'DevOps',
    'infrastructure': 'DevOps',
    
    'cloud': 'Cloud',
    'aws': 'Cloud',
    'azure': 'Cloud',
    'gcp': 'Cloud',
    'google cloud': 'Cloud',
}

POSITION_TECH_MAP = {
    'python': 'Python',
    'java': 'Java',
    'javascript': 'JavaScript',
    'js': 'JavaScript',
    'typescript': 'TypeScript',
    'ts': 'TypeScript',
    'react': 'React',
    'reactjs': 'React',
    'angular': 'Angular',
    'angularjs': 'Angular',
    'vue': 'Vue.js',
    'vue.js': 'Vue.js',
    'vuejs': 'Vue.js',
    'node': 'Node.js',
    'node.js': 'Node.js',
    'nodejs': 'Node.js',
    'django': 'Django',
    'flask': 'Flask',
    'flutter': 'Flutter',
    'swift': 'Swift',
    'kotlin': 'Kotlin',
    'c++': 'C++',
    'c#': 'C#',
    '.net': '.NET',
    'dotnet': '.NET',
    'dot net': '.NET',
    'sql': 'SQL',
    'mysql': 'MySQL',
    'postgresql': 'PostgreSQL',
    'postgres': 'PostgreSQL',
    'mongodb': 'MongoDB',
    'mongo': 'MongoDB',
    'docker': 'Docker',
    'kubernetes': 'Kubernetes',
    'k8s': 'Kubernetes',
    'aws': 'AWS',
    'amazon web services': 'AWS',
    'azure': 'Azure',
    'microsoft azure': 'Azure',
    'html/css': 'HTML/CSS',
    'tensorflow': 'TensorFlow',
    'pytorch': 'PyTorch',
    'pandas': 'Pandas',
    'numpy': 'NumPy',
    'scikit': 'Scikit-learn',
    'sklearn': 'Scikit-learn',
    'react native': 'React Native',
    'ionic': 'Ionic',
    'xamarin': 'Xamarin',
    'spring': 'Spring',
    'spring boot': 'Spring',
    'springboot': 'Spring',
    'redis': 'Redis',
    'nginx': 'Nginx',
    'go': 'Go',
    'golang': 'Go',
    'rust': 'Rust',
    'ruby': 'Ruby',
    'ruby on rails': 'Ruby',
    'rails': 'Ruby',
    'php': 'PHP',
    'wordpress': 'WordPress',
}


class Command(BaseCommand):
    help = 'Mezunların pozisyon, şirket ve deneyim açıklamalarına göre kategorilerini ve teknolojilerini günceller'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Değişiklik yapma, sadece ne olacağını göster',
        )
        parser.add_argument(
            '--db-path',
            type=str,
            default=os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))), 'linkedin_data.db'),
            help='LinkedIn veritabanı dosya yolu (eğitim açıklamaları için)',
        )

    def get_alumni_descriptions(self, alumni, db_path=None):
        """Mezunun tüm metin bilgilerini topla"""
        texts = []
        
        # Position ve company
        texts.append(alumni.current_position or '')
        texts.append(alumni.company or '')
        
        # WorkExperience descriptions
        experiences = WorkExperience.objects.filter(person=alumni)
        for exp in experiences:
            texts.append(exp.description or '')
            texts.append(exp.position or '')
            texts.append(exp.company or '')
        
        # LinkedIn veritabanından eğitim bilgilerini al
        if db_path and os.path.exists(db_path):
            try:
                conn = sqlite3.connect(db_path)
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                
                # Profil ID'sini bul
                cursor.execute(
                    "SELECT id FROM profiles WHERE name = ?",
                    (alumni.full_name,)
                )
                profile = cursor.fetchone()
                
                if profile:
                    # Eğitim açıklamalarını al
                    cursor.execute(
                        "SELECT description, degree FROM education WHERE profile_id = ?",
                        (profile['id'],)
                    )
                    for edu in cursor.fetchall():
                        texts.append(edu['description'] or '')
                        texts.append(edu['degree'] or '')
                    
                    # Deneyim açıklamalarını al
                    cursor.execute(
                        "SELECT description, position FROM experiences WHERE profile_id = ?",
                        (profile['id'],)
                    )
                    for exp in cursor.fetchall():
                        texts.append(exp['description'] or '')
                        texts.append(exp['position'] or '')
                
                conn.close()
            except Exception as e:
                print(f"Veritabanı hatası: {e}")
        
        # Tüm metinleri birleştir
        return ' '.join(texts).lower()

    def handle(self, *args, **options):
        dry_run = options.get('dry_run', False)
        db_path = options.get('db_path')
        
        # Get or create categories by name
        existing_cats = {c.name.lower(): c for c in ProjectCategory.objects.all()}
        print(f'Mevcut kategoriler: {list(existing_cats.keys())}')
        
        # Get or create technologies by name
        existing_techs = {t.name.lower(): t for t in Technology.objects.all()}
        print(f'Mevcut teknolojiler: {list(existing_techs.keys())}')
        
        alumni_list = Alumni.objects.all()
        updated_count = 0
        
        for alumni in alumni_list:
            # Tüm metin bilgilerini topla
            all_text = self.get_alumni_descriptions(alumni, db_path)
            
            # Find matching categories (avoid duplicates)
            matched_cats = []
            seen_cat_names = set()
            for keyword, cat_name in POSITION_CATEGORY_MAP.items():
                if keyword in all_text:
                    if cat_name.lower() in existing_cats and cat_name.lower() not in seen_cat_names:
                        matched_cats.append(existing_cats[cat_name.lower()])
                        seen_cat_names.add(cat_name.lower())
            
            # Find matching technologies (avoid duplicates)
            matched_techs = []
            seen_tech_names = set()
            for keyword, tech_name in POSITION_TECH_MAP.items():
                if keyword in all_text:
                    if tech_name.lower() in existing_techs and tech_name.lower() not in seen_tech_names:
                        matched_techs.append(existing_techs[tech_name.lower()])
                        seen_tech_names.add(tech_name.lower())
            
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