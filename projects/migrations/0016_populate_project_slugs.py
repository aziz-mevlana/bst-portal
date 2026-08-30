from django.db import migrations
from django.utils.text import slugify


def populate_project_slugs(apps, schema_editor):
    Project = apps.get_model('projects', 'Project')
    used = set(Project.objects.exclude(slug__isnull=True).exclude(slug='').values_list('slug', flat=True))
    for project in Project.objects.filter(slug__isnull=True).order_by('pk'):
        base = slugify(project.title) or f'proje-{project.pk}'
        candidate = base
        counter = 2
        while candidate in used:
            candidate = f'{base}-{counter}'
            counter += 1
        project.slug = candidate
        project.save(update_fields=['slug'])
        used.add(candidate)


class Migration(migrations.Migration):
    dependencies = [('projects', '0015_project_slug_nullable')]

    operations = [migrations.RunPython(populate_project_slugs, migrations.RunPython.noop)]
