from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('videos', '0032_message_read_forward'),
    ]

    operations = [
        migrations.AddField(
            model_name='message',
            name='is_edited',
            field=models.BooleanField(default=False),
        ),
    ]
