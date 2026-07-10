from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('videos', '0038_add_gift_thumbnail'),
    ]

    operations = [
        # Remove duplicate follower rows before adding the constraint
        migrations.RunSQL(
            sql="""
                DELETE FROM videos_follower
                WHERE id NOT IN (
                    SELECT MIN(id)
                    FROM videos_follower
                    GROUP BY user_id_id, follower_user_id_id
                );
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.AlterUniqueTogether(
            name='follower',
            unique_together={('user_id', 'follower_user_id')},
        ),
    ]
