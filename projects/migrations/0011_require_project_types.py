import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('projects', '0010_seed_project_taxonomy_and_map_legacy'),
    ]

    operations = [
        migrations.AlterField(
            model_name='project',
            name='project_type',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='projects',
                to='projects.projecttype',
            ),
        ),
        migrations.AlterField(
            model_name='projectrequest',
            name='project_type',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='requests',
                to='projects.projecttype',
            ),
        ),
    ]
