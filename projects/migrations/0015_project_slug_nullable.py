from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('projects', '0014_alter_projectachievement_evidence_file_and_more')]

    operations = [
        migrations.AddField(
            model_name='project',
            name='slug',
            field=models.SlugField(blank=True, max_length=220, null=True, unique=True),
        ),
    ]
