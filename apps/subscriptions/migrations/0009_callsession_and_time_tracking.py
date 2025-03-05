from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0004_availability"),
        ("subscriptions", "0008_usersubscription_video_calls_this_month"),
    ]

    operations = [
        migrations.AddField(
            model_name="usersubscription",
            name="video_seconds_consumed_this_month",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="usersubscription",
            name="voice_seconds_this_month",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.CreateModel(
            name="CallSession",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("uuid", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("call_type", models.CharField(choices=[("voice", "Voice"), ("video", "Video")], max_length=10)),
                ("channel_name", models.CharField(max_length=255, unique=True)),
                ("agora_uid_caller", models.PositiveIntegerField()),
                ("agora_uid_callee", models.PositiveIntegerField()),
                ("allowed_seconds", models.PositiveIntegerField(default=0)),
                ("consumed_seconds", models.PositiveIntegerField(default=0)),
                ("started_at", models.DateTimeField(auto_now_add=True)),
                ("answered_at", models.DateTimeField(blank=True, null=True)),
                ("ended_at", models.DateTimeField(blank=True, null=True)),
                ("status", models.CharField(choices=[("initiated", "Initiated"), ("ringing", "Ringing"), ("active", "Active"), ("ended", "Ended"), ("expired", "Expired"), ("missed", "Missed"), ("rejected", "Rejected"), ("failed", "Failed")], default="initiated", max_length=20)),
                ("ended_reason", models.CharField(blank=True, max_length=50, null=True)),
                ("agora_token_expire_at", models.DateTimeField(blank=True, null=True)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("callee", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="calls_received", to="users.user")),
                ("caller", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="calls_started", to="users.user")),
                ("subscription", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="call_sessions", to="subscriptions.usersubscription")),
            ],
            options={"ordering": ["-started_at"]},
        ),
    ]
