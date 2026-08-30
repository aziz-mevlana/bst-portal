import django.core.validators
import django.db.models.deletion
import events.models
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('events', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(model_name='event', name='allow_registration', field=models.BooleanField(default=False)),
        migrations.AddField(model_name='event', name='capacity', field=models.PositiveIntegerField(blank=True, null=True)),
        migrations.AddField(model_name='event', name='certificate_enabled', field=models.BooleanField(default=False)),
        migrations.AddField(model_name='event', name='registration_deadline', field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name='event', name='waitlist_enabled', field=models.BooleanField(default=True)),
        migrations.CreateModel(
            name='EventRegistration',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(choices=[('registered', 'Kayıtlı'), ('waitlisted', 'Bekleme listesinde'), ('attended', 'Katıldı'), ('cancelled', 'İptal edildi')], default='registered', max_length=12)),
                ('checkin_token', models.CharField(default=events.models.generate_checkin_token, editable=False, max_length=64, unique=True)),
                ('checked_in_at', models.DateTimeField(blank=True, null=True)),
                ('feedback_rating', models.PositiveSmallIntegerField(blank=True, null=True, validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(5)])),
                ('feedback_comment', models.TextField(blank=True)),
                ('feedback_at', models.DateTimeField(blank=True, null=True)),
                ('certificate_eligible', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('event', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='registrations', to='events.event')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='event_registrations', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['created_at'],
                'indexes': [models.Index(fields=['event', 'status', 'created_at'], name='event_registration_queue_idx')],
                'constraints': [models.UniqueConstraint(fields=('event', 'user'), name='unique_event_user_registration')],
            },
        ),
    ]
