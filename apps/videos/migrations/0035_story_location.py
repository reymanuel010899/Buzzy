from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('videos', '0034_favorite_track'),
    ]

    operations = [
        migrations.AddField(
            model_name='story',
            name='location',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
    ]
