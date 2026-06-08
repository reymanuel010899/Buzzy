from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0006_add_is_owner_to_user'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='onboarding_completed',
            field=models.BooleanField(default=False),
        ),
    ]
