import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('projects', '0017_require_project_slug')]

    operations = [
        migrations.CreateModel(
            name='ProjectRepository',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('repository_url', models.URLField(max_length=300)),
                ('owner', models.CharField(editable=False, max_length=100)),
                ('name', models.CharField(editable=False, max_length=100)),
                ('description', models.TextField(blank=True)),
                ('languages', models.JSONField(blank=True, default=dict)),
                ('github_updated_at', models.DateTimeField(blank=True, null=True)),
                ('stars', models.PositiveIntegerField(default=0)),
                ('forks', models.PositiveIntegerField(default=0)),
                ('contributor_count', models.PositiveIntegerField(default=0)),
                ('contributors', models.JSONField(blank=True, default=list)),
                ('release_count', models.PositiveIntegerField(default=0)),
                ('releases', models.JSONField(blank=True, default=list)),
                ('open_issue_count', models.PositiveIntegerField(default=0)),
                ('readme_url', models.URLField(blank=True)),
                ('sync_status', models.CharField(choices=[('pending', 'Senkronizasyon bekliyor'), ('synced', 'Güncel'), ('error', 'Senkronizasyon hatası'), ('rate_limited', 'GitHub limiti doldu')], default='pending', max_length=20)),
                ('sync_error', models.CharField(blank=True, max_length=300)),
                ('last_sync_attempt_at', models.DateTimeField(blank=True, null=True)),
                ('synced_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('project', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='repository', to='projects.project')),
            ],
            options={'ordering': ['project_id']},
        ),
    ]
