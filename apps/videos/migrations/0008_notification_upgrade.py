from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('videos', '0007_add_audio_metadata_to_video'),
    ]

    operations = [
        # 1. Rename old columns that will be replaced
        migrations.RenameField(
            model_name='notification',
            old_name='user_id',
            new_name='recipient',
        ),
        migrations.RenameField(
            model_name='notification',
            old_name='read_status',
            new_name='is_read',
        ),
        migrations.RenameField(
            model_name='notification',
            old_name='type',
            new_name='notification_type',
        ),

        # 2. Add new fields (nullable first so existing rows are OK)
        migrations.AddField(
            model_name='notification',
            name='actor',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='sent_notifications',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name='notification',
            name='video',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='notifications',
                to='videos.video',
            ),
        ),
        migrations.AddField(
            model_name='notification',
            name='comment',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='notifications',
                to='videos.comment',
            ),
        ),
        migrations.AddField(
            model_name='notification',
            name='read_at',
            field=models.DateTimeField(blank=True, null=True),
        ),

        # 3. Alter existing fields
        migrations.AlterField(
            model_name='notification',
            name='notification_type',
            field=models.CharField(
                choices=[
                    ('follow', 'Follow'),
                    ('like', 'Like'),
                    ('comment', 'Comment'),
                    ('comment_reply', 'Comment Reply'),
                    ('profile_visit', 'Profile Visit'),
                    ('story_like', 'Story Like'),
                    ('gift', 'Gift'),
                    ('mention', 'Mention'),
                ],
                default='follow',
                max_length=50,
            ),
        ),
        migrations.AlterField(
            model_name='notification',
            name='is_read',
            field=models.BooleanField(default=False, db_index=True),
        ),
        migrations.AlterField(
            model_name='notification',
            name='message',
            field=models.TextField(blank=True),
        ),
        migrations.AlterField(
            model_name='notification',
            name='recipient',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='notifications',
                to=settings.AUTH_USER_MODEL,
            ),
        ),

        # 4. Indexes and ordering
        migrations.AlterModelOptions(
            name='notification',
            options={'ordering': ['-created_at']},
        ),
        migrations.AddIndex(
            model_name='notification',
            index=models.Index(fields=['recipient', 'is_read'], name='notif_recipient_read_idx'),
        ),
        migrations.AddIndex(
            model_name='notification',
            index=models.Index(fields=['recipient', 'created_at'], name='notif_recipient_created_idx'),
        ),
    ]
