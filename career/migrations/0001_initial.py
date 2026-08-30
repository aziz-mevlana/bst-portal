import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = [
        ('alumni', '0005_remove_alumniprofile_tags_remove_alumniprofile_user_and_more'),
        ('projects', '0018_projectrepository'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='MentorshipProfile',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('is_available', models.BooleanField(default=False)),
                ('monthly_capacity', models.PositiveSmallIntegerField(default=2, validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(20)])),
                ('preferred_contact_method', models.CharField(choices=[('email', 'E-posta'), ('linkedin', 'LinkedIn'), ('website', 'Kişisel web sitesi')], default='email', max_length=12)),
                ('availability_note', models.CharField(blank=True, max_length=300)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('alumni', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='mentorship_profile', to='alumni.alumni')),
                ('mentoring_topics', models.ManyToManyField(blank=True, related_name='mentors', to='projects.projectcategory')),
            ],
            options={'ordering': ['alumni__full_name']},
        ),
        migrations.CreateModel(
            name='MentorshipRequest',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('goal', models.CharField(max_length=250)),
                ('message', models.TextField()),
                ('status', models.CharField(choices=[('pending', 'Bekliyor'), ('accepted', 'Kabul edildi'), ('rejected', 'Reddedildi'), ('completed', 'Tamamlandı'), ('cancelled', 'İptal edildi')], default='pending', max_length=12)),
                ('mentor_response', models.TextField(blank=True)),
                ('responded_at', models.DateTimeField(blank=True, null=True)),
                ('completed_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('mentor', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='requests', to='career.mentorshipprofile')),
                ('student', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='mentorship_requests', to=settings.AUTH_USER_MODEL)),
                ('topic', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='mentorship_requests', to='projects.projectcategory')),
            ],
            options={'ordering': ['-created_at']},
        ),
        migrations.CreateModel(
            name='MentorshipReview',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('rating', models.PositiveSmallIntegerField(validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(5)])),
                ('comment', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('mentorship_request', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='review', to='career.mentorshiprequest')),
            ],
        ),
        migrations.CreateModel(
            name='Opportunity',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=180)),
                ('slug', models.SlugField(blank=True, max_length=210, unique=True)),
                ('opportunity_type', models.CharField(choices=[('internship', 'Staj'), ('part_time', 'Part-time'), ('full_time', 'Full-time'), ('volunteer', 'Gönüllü proje'), ('freelance', 'Freelance'), ('teammate', 'Yarışma ekip arkadaşı')], max_length=20)),
                ('organization', models.CharField(max_length=180)),
                ('description', models.TextField()),
                ('requirements', models.TextField(blank=True)),
                ('location', models.CharField(blank=True, max_length=180)),
                ('work_mode', models.CharField(choices=[('onsite', 'Ofiste'), ('hybrid', 'Hibrit'), ('remote', 'Uzaktan')], max_length=12)),
                ('application_url', models.URLField(blank=True)),
                ('contact_method', models.CharField(choices=[('url', 'Başvuru bağlantısı'), ('email', 'E-posta'), ('portal', 'Portal profili')], default='url', max_length=12)),
                ('contact_email', models.EmailField(blank=True, max_length=254)),
                ('deadline', models.DateField(blank=True, null=True)),
                ('approval_status', models.CharField(choices=[('pending', 'Onay bekliyor'), ('approved', 'Onaylandı'), ('rejected', 'Reddedildi')], default='pending', max_length=12)),
                ('approved_at', models.DateTimeField(blank=True, null=True)),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('approved_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='opportunities_approved', to=settings.AUTH_USER_MODEL)),
                ('created_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='opportunities_created', to=settings.AUTH_USER_MODEL)),
                ('technologies', models.ManyToManyField(blank=True, related_name='opportunities', to='projects.technology')),
            ],
            options={'ordering': ['-created_at']},
        ),
        migrations.AddIndex(model_name='mentorshiprequest', index=models.Index(fields=['mentor', 'status', '-created_at'], name='mentor_request_inbox_idx')),
        migrations.AddConstraint(model_name='mentorshiprequest', constraint=models.UniqueConstraint(condition=models.Q(('status__in', ['pending', 'accepted'])), fields=('student', 'mentor'), name='unique_active_student_mentor_request')),
        migrations.AddIndex(model_name='opportunity', index=models.Index(fields=['approval_status', 'is_active', 'deadline'], name='opportunity_public_idx')),
        migrations.AddIndex(model_name='opportunity', index=models.Index(fields=['opportunity_type', 'work_mode'], name='opportunity_type_mode_idx')),
    ]
