from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("subscriptions", "0007_usersubscription_ai_generations_this_month_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="usersubscription",
            name="video_calls_this_month",
            field=models.PositiveIntegerField(default=0),
        ),
    ]
