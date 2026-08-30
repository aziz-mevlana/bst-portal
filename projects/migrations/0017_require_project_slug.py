from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('projects', '0016_populate_project_slugs')]

    operations = [
        migrations.AlterField(
            model_name='project',
            name='slug',
            field=models.SlugField(blank=True, max_length=220, unique=True),
        ),
    ]
