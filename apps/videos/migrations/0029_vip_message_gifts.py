from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('videos', '0028_usergift'),
    ]

    operations = [
        migrations.AddField(
            model_name='videogift',
            name='vip_message',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='usergift',
            name='vip_message',
            field=models.TextField(blank=True, default=''),
        ),
    ]
