from django.db import migrations


class Migration(migrations.Migration):
    """
    Desacopla la IA de las suscripciones.
    Los créditos de IA ahora viven en AIWallet (videos/models.py).
    """

    dependencies = [
        ('subscriptions', '0005_add_ai_bonus_credits'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='usersubscription',
            name='ai_generations_this_month',
        ),
        migrations.RemoveField(
            model_name='usersubscription',
            name='ai_image_generations_this_month',
        ),
        migrations.RemoveField(
            model_name='usersubscription',
            name='ai_video_bonus',
        ),
        migrations.RemoveField(
            model_name='usersubscription',
            name='ai_image_bonus',
        ),
    ]
