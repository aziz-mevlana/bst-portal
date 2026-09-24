from datetime import datetime
from zoneinfo import ZoneInfo

from django.db import migrations


def ensure_fall_term(apps, schema_editor):
    Term = apps.get_model('capstone', 'CapstoneTerm')
    alias = schema_editor.connection.alias
    has_active_term = Term.objects.using(alias).filter(is_active=True).exists()
    fall = Term.objects.using(alias).filter(academic_year='2026-2027', semester='FALL').first()
    if fall is None:
        istanbul = ZoneInfo('Europe/Istanbul')
        Term.objects.using(alias).create(
            academic_year='2026-2027', semester='FALL',
            starts_at=datetime(2026, 9, 14, 0, 0, tzinfo=istanbul),
            midterm_at=datetime(2026, 11, 7, 0, 0, tzinfo=istanbul),
            final_at=datetime(2026, 12, 26, 0, 0, tzinfo=istanbul),
            is_active=not has_active_term,
        )
    elif not has_active_term:
        Term.objects.using(alias).filter(pk=fall.pk).update(is_active=True)


class Migration(migrations.Migration):
    dependencies = [
        ('capstone', '0008_capstoneenrollment_advisor_and_more'),
        ('projects', '0027_course_catalog_2026_2027'),
    ]

    operations = [
        migrations.RunPython(ensure_fall_term, migrations.RunPython.noop),
    ]
