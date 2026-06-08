from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('videos', '0030_merge_20260510_1641'),
    ]

    operations = [
        migrations.AddField(
            model_name='storygift',
            name='is_seen',
            field=models.BooleanField(default=False),
        ),
    ]
