from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('videos', '0021_story_filter_css'),
    ]

    operations = [
        migrations.AddField(
            model_name='story',
            name='sticker_layers',
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name='story',
            name='text_layers',
            field=models.JSONField(blank=True, default=list),
        ),
    ]
