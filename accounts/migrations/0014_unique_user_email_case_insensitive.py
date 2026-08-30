from django.db import migrations


def ensure_no_duplicate_emails(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "SELECT LOWER(email), COUNT(*) FROM auth_user "
            "WHERE email IS NOT NULL AND email <> '' "
            "GROUP BY LOWER(email) HAVING COUNT(*) > 1"
        )
        duplicates = cursor.fetchall()
    if duplicates:
        values = ', '.join(f'{email} ({count})' for email, count in duplicates[:20])
        raise RuntimeError(
            'Case-insensitive tekrar eden e-postalar bulundu; veri silinmedi. '
            f'Yönetici incelemesi gerekiyor: {values}'
        )


class Migration(migrations.Migration):
    dependencies = [('accounts', '0013_profile_unique_nonempty_student_number')]

    operations = [
        migrations.RunPython(ensure_no_duplicate_emails, migrations.RunPython.noop),
        migrations.RunSQL(
            sql="CREATE UNIQUE INDEX unique_auth_user_email_ci ON auth_user (LOWER(email)) WHERE email IS NOT NULL AND email <> ''",
            reverse_sql="DROP INDEX IF EXISTS unique_auth_user_email_ci",
        ),
    ]
