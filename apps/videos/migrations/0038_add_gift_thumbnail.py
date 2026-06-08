from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('videos', '0037_add_saved_video'),
    ]

    operations = [
        migrations.AddField(
            model_name='giftstory',
            name='thumbnail',
            field=models.ImageField(
                blank=True,
                null=True,
                upload_to='gifts/thumbnails/',
                help_text='Frame extraído del video del regalo',
            ),
        ),
    ]
