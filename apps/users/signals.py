from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth import get_user_model
from apps.videos.models import UserOnlineStatus


User = get_user_model()

@receiver(post_save, sender=User)
def create_user_online_status(sender, instance, created, **kwargs):
    if created:
        UserOnlineStatus.objects.create(user=instance)