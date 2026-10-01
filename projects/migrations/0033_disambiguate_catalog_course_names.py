"""Show both PDF titles instead of arbitrarily choosing the first source row.

Only the three known source collisions and their exact official names qualify.
Custom historical titles, IDs and relations are preserved. Reverse is a no-op:
restoring the ambiguous first title would lose source information.
"""
import unicodedata
from django.db import migrations


COLLISIONS = {
    'BST421': ('İletişim Teknikleri', 'Yapay Zekâ Programlama'),
    'BST425': ('Kamu Ekonomisi', 'Gömülü Sistemler'),
    'BST427': ('Yerel Yönetimler', 'Bulanık Mantık'),
}


def disambiguate_names(apps, schema_editor):
    Course = apps.get_model('projects', 'Course')
    alias = schema_editor.connection.alias
    for course in Course.objects.using(alias).all().iterator():
        code = ''.join(unicodedata.normalize('NFKC', course.code).split()).upper()
        names = COLLISIONS.get(code)
        if names and course.name in names:
            Course.objects.using(alias).filter(pk=course.pk, name=course.name).update(name=' / '.join(names))


class Migration(migrations.Migration):
    dependencies = [('projects', '0032_courseprivateevaluation_courseprojecttemplate_and_more')]
    operations = [migrations.RunPython(disambiguate_names, migrations.RunPython.noop)]
