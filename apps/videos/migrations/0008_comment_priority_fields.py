from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("videos", "0007_videostats"),
    ]

    operations = [
        migrations.AddField(
            model_name="comment",
            name="is_priority_comment",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="comment",
            name="priority_plan_name",
            field=models.CharField(
                blank=True,
                choices=[("VIP", "VIP"), ("PLUS", "PLUS"), ("FRIEND", "FRIEND")],
                max_length=20,
                null=True,
            ),
        ),
    ]
