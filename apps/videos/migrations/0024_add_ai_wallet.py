from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('videos', '0023_add_story_report'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='AIWallet',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('video_credits', models.PositiveIntegerField(default=0, help_text='Créditos de video disponibles')),
                ('image_credits', models.PositiveIntegerField(default=0, help_text='Créditos de imagen disponibles')),
                ('total_videos_generated', models.PositiveIntegerField(default=0, help_text='Videos generados histórico')),
                ('total_images_generated', models.PositiveIntegerField(default=0, help_text='Imágenes generadas histórico')),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('user', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='ai_wallet',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'verbose_name': 'AI Wallet',
                'verbose_name_plural': 'AI Wallets',
            },
        ),
    ]
