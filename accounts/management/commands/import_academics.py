from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import Profile


ACADEMICS = [
    {
        'email': 'murattopaloglu@trakya.edu.tr',
        'first_name': 'Murat',
        'last_name': 'TOPALOĞLU',
        'title': 'doc_dr',
    },
    {
        'email': 'egementekkanat@trakya.edu.tr',
        'first_name': 'Egemen',
        'last_name': 'TEKKANAT',
        'title': 'dr_ogr_uyesi',
    },
    {
        'email': 'harunozkisi@trakya.edu.tr',
        'first_name': 'Harun',
        'last_name': 'ÖZKİŞİ',
        'title': 'dr_ogr_uyesi',
    },
    {
        'email': 'onurkara@trakya.edu.tr',
        'first_name': 'Onur',
        'last_name': 'KARA',
        'title': 'ogretim_gorevlisi',
    },
]


class Command(BaseCommand):
    help = 'Resmi bölüm kadrosundaki akademisyenleri silmeden ekler veya günceller.'

    @transaction.atomic
    def handle(self, *args, **options):
        created_count = 0
        updated_count = 0

        for data in ACADEMICS:
            email = data['email'].lower()
            user = User.objects.filter(email__iexact=email).first()
            created = user is None
            if created:
                username_base = email.split('@', 1)[0]
                username = username_base
                suffix = 1
                while User.objects.filter(username=username).exists():
                    suffix += 1
                    username = f'{username_base}{suffix}'
                user = User(username=username, email=email)
                user.set_unusable_password()

            user.email = email
            user.first_name = data['first_name']
            user.last_name = data['last_name']
            user.is_active = True
            user.save()

            profile, _ = Profile.objects.get_or_create(user=user)
            profile.user_type = 'teacher'
            profile.teacher_title = data['title']
            profile.department = 'Bilişim Sistemleri ve Teknolojileri'
            profile.save()

            if created:
                created_count += 1
            else:
                updated_count += 1

        self.stdout.write(self.style.SUCCESS(
            f'Akademisyen aktarımı tamamlandı: {created_count} oluşturuldu, '
            f'{updated_count} güncellendi, hiçbir kayıt silinmedi.'
        ))
