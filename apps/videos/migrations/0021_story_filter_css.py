from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('videos', '0020_story_audio_track_artist_story_audio_track_title_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='story',
            name='filter_css',
            field=models.CharField(blank=True, max_length=500, null=True),
        ),
    ]
