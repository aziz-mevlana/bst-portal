import sqlite3
import os
import re
from datetime import datetime, date
from django.core.management.base import BaseCommand
from alumni.models import Alumni


class Command(BaseCommand):
    help = 'Mezun-Board SQLite veritabanından mezun verilerini içe aktarır'

    def add_arguments(self, parser):
        parser.add_argument(
            '--db-path',
            type=str,
            default=os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))), 'Mezun-Board-main', 'linkedin_data.db'),
            help='SQLite veritabanı dosya yolu',
        )
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Mevcut user=None mezun kayıtlarını sil ve yeniden yükle',
        )

    def handle(self, *args, **options):
        db_path = options['db_path']
        
        if not os.path.exists(db_path):
            self.stderr.write(f'Veritabanı dosyası bulunamadı: {db_path}')
            return

        if options['clear']:
            deleted_count = Alumni.objects.filter(user__isnull=True).delete()[0]
            self.stdout.write(f'{deleted_count} adet user=None mezun kaydı silindi.')

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Profilleri al
        cursor.execute("SELECT * FROM profiles ORDER BY id")
        profiles = cursor.fetchall()

        created_count = 0
        skipped_count = 0

        for profile in profiles:
            profile_id = profile['id']
            name = profile['name'] or ''
            linkedin_url = profile['linkedin_url'] or ''
            profile_photo = profile['profile_photo'] or ''

            # Aynı isimde zaten kayıt var mı kontrol et
            if Alumni.objects.filter(full_name=name, user__isnull=True).exists():
                skipped_count += 1
                continue

            # İlk deneyimi al (current position)
            cursor.execute(
                "SELECT * FROM experiences WHERE profile_id = ? ORDER BY id LIMIT 1",
                (profile_id,)
            )
            experience = cursor.fetchone()
            current_position = experience['position'] if experience else ''
            company = experience['company'] if experience else ''
            
            # Şirket adını temizle (örn: "Evalan · Tam zamanlı" -> "Evalan")
            if company and '·' in company:
                company = company.split('·')[0].strip()

            # Mezuniyet yılını eğitim bilgisinden çıkar
            cursor.execute(
                "SELECT * FROM education WHERE profile_id = ? ORDER BY id",
                (profile_id,)
            )
            educations = cursor.fetchall()
            graduation_year = None
            
            for edu in educations:
                date_range = edu['date_range'] or ''
                # "2010 - 2014" veya "2010-2014" formatından yılı çıkar
                year_match = re.findall(r'(\d{4})', date_range)
                if year_match:
                    graduation_year = int(year_match[-1])  # Son yıl mezuniyet yılı
                    break

            # Deneyim seviyesini belirle (yıl sayısına göre)
            experience_level = 'junior'
            cursor.execute(
                "SELECT COUNT(*) as exp_count FROM experiences WHERE profile_id = ?",
                (profile_id,)
            )
            exp_count = cursor.fetchone()['exp_count']
            if exp_count >= 4:
                experience_level = 'senior'
            elif exp_count >= 2:
                experience_level = 'mid_level'

            # Alumni kaydı oluştur
            alumni = Alumni.objects.create(
                full_name=name,
                linkedin_url=linkedin_url,
                profile_photo=profile_photo,
                current_position=current_position,
                company=company,
                graduation_year=graduation_year,
                experience_level=experience_level,
                bio='',
                is_show_in_alumni_list=False,
            )
            created_count += 1

            # İlk 3 deneyimi WorkExperience olarak ekle
            cursor.execute(
                "SELECT * FROM experiences WHERE profile_id = ? ORDER BY id LIMIT 3",
                (profile_id,)
            )
            experiences = cursor.fetchall()
            
            from alumni.models import WorkExperience
            for exp in experiences:
                exp_company = exp['company'] or ''
                if '·' in exp_company:
                    exp_company = exp_company.split('·')[0].strip()
                
                WorkExperience.objects.create(
                    person=alumni,
                    company=exp_company,
                    position=exp['position'] or '',
                    start_date=date.today(),
                    is_current=False,
                    description=exp['description'] or '',
                )

        conn.close()

        self.stdout.write(self.style.SUCCESS(
            f'İçe aktarma tamamlandı: {created_count} mezun oluşturuldu, {skipped_count} atlandı.'
        ))
