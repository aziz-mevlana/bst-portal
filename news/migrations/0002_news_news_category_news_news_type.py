# Generated by Django 5.2.1 on 2025-05-27 12:51

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('news', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='news',
            name='news_category',
            field=models.CharField(blank=True, max_length=100, null=True, verbose_name='Haber Kategorisi'),
        ),
        migrations.AddField(
            model_name='news',
            name='news_type',
            field=models.CharField(blank=True, max_length=100, null=True, verbose_name='Haber Tipi'),
        ),
    ]
