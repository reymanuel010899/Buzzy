from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0007_add_onboarding_completed'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='sms_attempts',
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='user',
            name='sms_blocked_until',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='user',
            name='phone_number',
            field=models.CharField(blank=True, max_length=20, null=True, unique=True),
        ),
    ]
