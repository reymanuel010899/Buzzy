from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('videos', '0016_gift_premium_exclusive'),
    ]

    operations = [
        migrations.CreateModel(
            name='AudioTrack',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=255)),
                ('artist', models.CharField(max_length=255)),
                ('cover', models.ImageField(blank=True, null=True, upload_to='audio_tracks/covers/')),
                ('audio_file', models.FileField(upload_to='audio_tracks/files/')),
                ('duration_secs', models.PositiveIntegerField(default=0)),
                ('category', models.CharField(
                    choices=[
                        ('trending', 'Tendencias'),
                        ('pop', 'Pop'),
                        ('urban', 'Urban'),
                        ('electronic', 'Electronic'),
                        ('latin', 'Latin'),
                        ('chill', 'Chill'),
                    ],
                    default='trending',
                    max_length=20,
                )),
                ('is_active', models.BooleanField(default=True)),
                ('play_count', models.PositiveIntegerField(default=0, editable=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'ordering': ['-play_count', '-created_at'],
            },
        ),
    ]
