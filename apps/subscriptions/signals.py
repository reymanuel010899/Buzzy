from django.db.models.signals import post_save
from django.dispatch import receiver
from apps.users.models import User
from .models import UserSubscription

@receiver(post_save, sender=User)
def create_user_subscription(sender, instance, created, **kwargs):
    if created:
        UserSubscription.objects.create(user=instance)
