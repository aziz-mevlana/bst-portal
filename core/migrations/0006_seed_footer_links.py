from django.db import migrations


DEFAULTS = {
    'navigation': [('Ana Sayfa', '/'), ('Etkinlikler', '/events/'), ('Haberler', '/news/'), ('Projeler', '/projects/'), ('Mezunlar', '/alumni/')],
    'resources': [
        ('Bölüm Web Sitesi', 'https://kycubyo-bilisimsistemleri.trakya.edu.tr/'),
        ('Ders Kataloğu', 'https://bys.trakya.edu.tr/file/open/20295154'),
        ('Akademik Kadro', 'https://kycubyo-bilisimsistemleri.trakya.edu.tr/staff/bilisim-sistemleri-ve-teknolojileri'),
    ],
    'contact': [('bstakademi@outlook.com', 'mailto:bstakademi@outlook.com'), ('GitHub', 'https://github.com/bstportal'), ('LinkedIn', 'https://www.linkedin.com/in/bst-akademi/?originalSubdomain=tr')],
    'legal': [('Gizlilik Politikası', '/legal/privacy/'), ('KVKK', '/legal/kvkk/'), ('Kullanım Koşulları', '/legal/terms/')],
    'contributors': [('Mevlana', 'https://linkedin.com/in/aziz-alim/'), ('Oğuzhan Bodur', 'https://www.linkedin.com/in/oguzhan-bodur/')],
}


def seed(apps, schema_editor):
    FooterLink = apps.get_model('core', 'FooterLink')
    for section, links in DEFAULTS.items():
        for order, (label, url) in enumerate(links):
            FooterLink.objects.using(schema_editor.connection.alias).get_or_create(
                section=section, label=label,
                defaults={'url': url, 'sort_order': order, 'open_new_tab': url.startswith('https://')},
            )


class Migration(migrations.Migration):
    dependencies = [('core', '0005_footerlink')]
    # Preserve subsequently edited links when reversing this data migration.
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
