from django.db import migrations, models

import accounts.validators


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0020_profile_must_change_password'),
    ]

    operations = [
        migrations.AlterField(
            model_name='portfoliocertificate',
            name='credential_url',
            field=models.URLField(blank=True, validators=[accounts.validators.validate_public_website]),
        ),
    ]
