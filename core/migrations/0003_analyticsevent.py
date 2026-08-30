from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('core', '0002_notification')]

    operations = [
        migrations.CreateModel(
            name='AnalyticsEvent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('event_type', models.CharField(choices=[('profile_view', 'Profil görüntüleme'), ('demo_click', 'Demo tıklama'), ('github_click', 'GitHub tıklama'), ('event_registration', 'Etkinlik kaydı'), ('mentorship_request', 'Mentorluk talebi'), ('search', 'Arama'), ('ai_answer', 'AI yanıtı'), ('company_contact', 'Şirket iletişim talebi')], db_index=True, max_length=32)),
                ('target_type', models.CharField(blank=True, max_length=80)),
                ('target_id', models.CharField(blank=True, max_length=80)),
                ('visitor_hash', models.CharField(max_length=64)),
                ('succeeded', models.BooleanField(blank=True, null=True)),
                ('metadata', models.JSONField(blank=True, default=dict)),
                ('date_bucket', models.DateField(db_index=True)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
            ],
            options={'ordering': ['-created_at']},
        ),
        migrations.AddConstraint(
            model_name='analyticsevent',
            constraint=models.UniqueConstraint(fields=('event_type', 'target_type', 'target_id', 'visitor_hash', 'date_bucket'), name='unique_daily_analytics_event'),
        ),
        migrations.AddIndex(model_name='analyticsevent', index=models.Index(fields=['event_type', 'date_bucket'], name='analytics_type_date_idx')),
    ]
