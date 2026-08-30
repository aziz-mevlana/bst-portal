from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0006_secure_verification_codes'),
    ]

    operations = [
        migrations.AlterField(
            model_name='profile',
            name='teacher_title',
            field=models.CharField(
                blank=True,
                choices=[
                    ('', 'Ünvan Seçin'),
                    ('prof_dr', 'Prof. Dr.'),
                    ('doc_dr', 'Doç. Dr.'),
                    ('dr_ogr_uyesi', 'Dr. Öğr. Üyesi'),
                    ('dr', 'Dr.'),
                    ('arastirma_gorevlisi', 'Araştırma Görevlisi'),
                    ('ogretim_gorevlisi', 'Öğretim Görevlisi'),
                    ('okutman', 'Okutman'),
                    ('uzman', 'Uzman'),
                ],
                max_length=30,
                null=True,
            ),
        ),
    ]
