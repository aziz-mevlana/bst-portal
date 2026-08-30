from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('core', '0001_initial'), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]

    operations = [
        migrations.CreateModel(
            name='Notification',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('notification_type', models.CharField(choices=[('project_comment', 'Proje yorumu'), ('project_update', 'Proje güncellemesi'), ('project_approved', 'Proje onayı'), ('application_accepted', 'Başvuru kabulü'), ('application_rejected', 'Başvuru reddi'), ('mentorship_request', 'Mentorluk talebi'), ('opportunity', 'Kariyer ilanı'), ('event', 'Etkinlik'), ('system', 'Sistem')], db_index=True, max_length=32)),
                ('message', models.CharField(max_length=300)),
                ('target_url', models.CharField(blank=True, max_length=500)),
                ('read_at', models.DateTimeField(blank=True, db_index=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('actor', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='notifications_created', to=settings.AUTH_USER_MODEL)),
                ('recipient', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='notifications', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-created_at']},
        ),
        migrations.AddIndex(
            model_name='notification',
            index=models.Index(fields=['recipient', 'read_at', '-created_at'], name='notification_inbox_idx'),
        ),
    ]
