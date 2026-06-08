from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("videos", "0006_add_audio_fields_to_video"),
    ]

    operations = [
        migrations.AddField(
            model_name="video",
            name="audio_track_id",
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
        migrations.AddField(
            model_name="video",
            name="audio_track_title",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name="video",
            name="audio_track_artist",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name="video",
            name="audio_track_cover",
            field=models.URLField(blank=True, max_length=500, null=True),
        ),
    ]
