from django.conf import settings
from django.db import migrations, models
import apps.videos.models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('videos', '0027_videogift_is_seen'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='UserGift',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('uuid', models.CharField(blank=True, default=apps.videos.models.full_uuid, max_length=32, unique=True)),
                ('gift_type', models.CharField(max_length=20)),
                ('quantity', models.PositiveIntegerField(default=1)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('is_active', models.BooleanField(default=True)),
                ('is_seen', models.BooleanField(default=False)),
                ('gift', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='user_sent_gifts', to='videos.giftstory')),
                ('recipient', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='received_user_gifts', to=settings.AUTH_USER_MODEL)),
                ('sender', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='sent_user_gifts', to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]
