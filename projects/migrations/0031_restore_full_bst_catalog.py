"""Catalog transcribed from docs/mufredat.pdf, pages 1–2.

The PDF repeats BST421/425/427 under distinct titles. One code remains one
Course; both verbatim titles are retained in the catalog display name.
Historical Course names and all object IDs remain untouched.
"""
import unicodedata
from django.db import migrations
from django.utils.text import slugify

ROWS = ((1, 'BST 103', 'Algoritma Bilgisayar Programla. Giriş'), (1, 'BST 105', 'Bilgisayara Giriş'), (2, 'BST 104', 'Bilgisayar Programlama'), (3, 'BST 201', 'Veri Yapıları'), (3, 'BST 203', 'Sayısal Devre Tasarımı'), (3, 'BST 205', 'İstatistik'), (3, 'BST 207', 'Python Programlama'), (3, 'BST 209', 'Nesne Tabanlı Programlama'), (3, 'BST 211', 'Sanallaştırma Ve Bulut Hesaplama'), (4, 'BST 202', 'Prog. Dil. Uygulamaları'), (4, 'BST 204', 'Bilişimde Veri Güvenliği'), (4, 'BST 206', 'Bilgisayar Mimarisi'), (4, 'BST 208', 'Linux Sistemleri Yönetimi'), (4, 'BST 210', 'Kriptografi'), (4, 'BST 212', 'Proje Yönetimi'), (5, 'BST 301', 'Görsel Programlama-I'), (5, 'BST 303', 'Yazılım Mühendisliği'), (5, 'BST 305', 'İşletim Sistemleri'), (5, 'BST 307', 'İnternet Programlama'), (5, 'BST 321', 'İnsan Kaynakları Yönetimi'), (5, 'BST 323', 'Liderlik'), (5, 'BST 325', 'Araştırma Yöntemleri'), (5, 'BST 337', 'Halkla İlişkiler'), (5, 'BST 327', 'Tüketici ve Üretici Davranışları'), (5, 'BST 329', 'Yönetim Muhasebesi'), (5, 'BST 399', 'Kamu Maliyesi ve Devlet Bütçesi'), (5, 'BST 331', 'İşletme Enformatik Sistemleri'), (5, 'BST 333', 'İnovasyon'), (5, 'BST 335', 'Doğal Dil İşleme'), (6, 'BST 302', 'Görsel Programlama-II'), (6, 'BST 304', 'Veritabanı Yönetim Sistemleri'), (6, 'BST 306', 'Bilgisayar Ağlarına Giriş'), (6, 'BST 308', 'Mikroişlemciler'), (6, 'BST 326', 'E-Ticaret'), (6, 'BST 328', 'Girişimcilik ve İş Tasarımı'), (6, 'BST 330', 'Hizmet Pazarlaması'), (6, 'BST 332', 'Yönetim Psikolojisi'), (6, 'BST 334', 'İşletme Finansı'), (6, 'BST 336', 'Karar Verme Teknikleri'), (6, 'BST 392', 'Vergi Hukuku'), (6, 'BST 320', 'Sosyal Ağ ve Büyük Veri Analizleri'), (6, 'BST 322', 'Yapay Sinir Ağları'), (6, 'BST 324', 'Automata'), (7, 'BST 401', 'Bitirme Projesi-I'), (7, 'BST 403', 'Veritabanı Yönetim Sistemleri'), (7, 'BST 405', 'Bilgisayar Ağ Yönetimi'), (7, 'BST 407', 'Mesleki İngilizce I'), (7, 'BST 421', 'İletişim Teknikleri'), (7, 'BST 499', 'Türk Vergi Sistemi'), (7, 'BST 425', 'Kamu Ekonomisi'), (7, 'BST 427', 'Yerel Yönetimler'), (7, 'BST 421', 'Yapay Zekâ Programlama'), (7, 'BST 423', 'Mobil Uygulama Geliştirme-I'), (7, 'BST 425', 'Gömülü Sistemler'), (7, 'BST 427', 'Bulanık Mantık'), (7, 'BST 429', 'Veri Madenciliği'), (7, 'BST 431', 'Bilgisayar Grafikleri'), (8, 'BST 402', 'Bitirme Projesi-II'), (8, 'BST 404', 'Sistem Programlama'), (8, 'BST 406', 'Mesleki İngilizce II'), (8, 'BST 420', 'Stratejik Yönetim'), (8, 'BST 422', 'Uluslararası Maliye'), (8, 'BST 498', 'Mali Yargı'), (8, 'BST 424', 'Uluslararası Vergi Rekabeti'), (8, 'BST 426', 'Mobil Uygulama Geliştirme-II'), (8, 'BST 428', 'Sızma Testleri Ve Etik Hackleme'), (8, 'BST 430', 'İş Süreçleri Yönetimi'), (8, 'BST 432', 'Yönetim ve Organizasyon'), (8, 'BST 434', 'Robotik Bilim'), (8, 'BST 436', 'Sistem Analizi'))


def normalized(code):
    return ''.join(unicodedata.normalize('NFKC', code).split()).upper()


def restore_catalog(apps, schema_editor):
    Course = apps.get_model('projects', 'Course')
    Entry = apps.get_model('projects', 'CourseCatalogEntry')
    alias = schema_editor.connection.alias
    courses = {}
    for course in Course.objects.using(alias).all():
        courses.setdefault(normalized(course.code), []).append(course)
    grouped = {}
    for semester, code, name in ROWS:
        key = (semester, normalized(code))
        grouped.setdefault(key, {'code': code, 'names': []})['names'].append(name)
    allowed = set()
    for (semester, key), row in grouped.items():
        matches = courses.get(key, [])
        if len(matches) > 1:
            raise ValueError(f'{key}: duplicate historical Course records require manual reconciliation.')
        if matches:
            course = matches[0]
        else:
            slug = base = slugify(row['code'])
            n = 2
            while Course.objects.using(alias).filter(slug=slug).exists():
                slug = f'{base}-{n}'
                n += 1
            course = Course.objects.using(alias).create(code=row['code'], name=row['names'][0], slug=slug)
            courses[key] = [course]
        season = 'FALL' if semester % 2 else 'SPRING'
        Entry.objects.using(alias).update_or_create(course_id=course.pk,
            academic_year='2026-2027', semester=season,
            defaults={'class_level': (semester + 1) // 2,
                      'display_name': ' / '.join(row['names']), 'is_active': True})
        allowed.add((course.pk, season))
    # Archive catalog rows only, never delete historical courses or relations.
    for entry in Entry.objects.using(alias).filter(academic_year='2026-2027', is_active=True):
        if (entry.course_id, entry.semester) not in allowed:
            Entry.objects.using(alias).filter(pk=entry.pk).update(is_active=False)


class Migration(migrations.Migration):
    dependencies = [('projects', '0030_courseprojectassignment_cancellation_reason_and_more')]
    operations = [migrations.RunPython(restore_catalog, migrations.RunPython.noop)]
