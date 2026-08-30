from django.db import migrations, models
from django.utils.text import slugify


def fill_public_slugs(apps, schema_editor):
    Profile = apps.get_model('accounts', 'Profile')
    used = set(Profile.objects.exclude(public_slug__isnull=True).values_list('public_slug', flat=True))
    for profile in Profile.objects.select_related('user').order_by('pk').iterator():
        if profile.public_slug:
            continue
        full_name = f'{profile.user.first_name} {profile.user.last_name}'.strip()
        base = slugify(full_name or profile.user.username) or f'user-{profile.user_id}'
        candidate = base
        counter = 2
        while candidate in used:
            candidate = f'{base}-{counter}'
            counter += 1
        Profile.objects.filter(pk=profile.pk).update(public_slug=candidate)
        used.add(candidate)


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0008_profile_bio_profile_featured_from_and_more'),
    ]

    operations = [
        migrations.RunPython(fill_public_slugs, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='profile',
            name='public_slug',
            field=models.SlugField(blank=True, max_length=170, unique=True),
        ),
    ]
