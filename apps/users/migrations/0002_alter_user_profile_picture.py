# Generated by Django 5.1.6 on 2025-02-20 04:32

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='user',
            name='profile_picture',
            field=models.ImageField(blank=True, default='profile_pics/avatar.webp', null=True, upload_to='profile_pics/'),
        ),
    ]
