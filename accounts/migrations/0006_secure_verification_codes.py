from django.contrib.auth.hashers import make_password
from django.db import migrations, models


def migrate_plaintext_passwords(apps, schema_editor):
    EmailVerification = apps.get_model('accounts', 'EmailVerification')
    for verification in EmailVerification.objects.all().iterator():
        data = dict(verification.session_data or {})
        plaintext = data.pop('password', None)
        update_fields = []
        if plaintext and not verification.password_hash:
            verification.password_hash = make_password(plaintext)
            update_fields.append('password_hash')
        if plaintext is not None:
            verification.session_data = data
            update_fields.append('session_data')
        if update_fields:
            verification.save(update_fields=update_fields)


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0005_profile_teacher_title_alter_profile_user_type_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='emailverification',
            name='password_hash',
            field=models.CharField(blank=True, max_length=128),
        ),
        migrations.AddField(
            model_name='emailverification',
            name='failed_attempts',
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='passwordreset',
            name='failed_attempts',
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.RunPython(migrate_plaintext_passwords, migrations.RunPython.noop),
    ]
