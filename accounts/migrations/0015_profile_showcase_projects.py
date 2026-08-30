from django.db import migrations, models
from django.db.models import Q


def seed_existing_showcases(apps, schema_editor):
    """Preserve projects that existing public portfolios already displayed."""

    Profile = apps.get_model('accounts', 'Profile')
    Project = apps.get_model('projects', 'Project')
    for profile in Profile.objects.iterator():
        project_ids = Project.objects.filter(
            Q(created_by_id=profile.user_id) | Q(team__id=profile.user_id),
            visibility='public',
            approval_status='approved',
            development_status='completed',
        ).values_list('pk', flat=True).distinct()
        profile.showcase_projects.add(*project_ids)


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0014_unique_user_email_case_insensitive'),
        ('projects', '0020_alter_projectcategory_options_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='profile',
            name='showcase_projects',
            field=models.ManyToManyField(
                blank=True,
                related_name='showcased_by_profiles',
                to='projects.project',
                verbose_name='Profilde sergilenen projeler',
            ),
        ),
        migrations.RunPython(seed_existing_showcases, migrations.RunPython.noop),
    ]
