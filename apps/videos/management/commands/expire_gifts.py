from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from apps.videos.models import UserGift, VideoGift, StoryGift


class Command(BaseCommand):
    help = 'Elimina regalos no abiertos después de 30 días'

    def handle(self, *args, **kwargs):
        cutoff = timezone.now() - timedelta(days=30)

        user_expired = UserGift.objects.filter(is_seen=False, created_at__lt=cutoff)
        user_count = user_expired.count()
        user_expired.delete()

        video_expired = VideoGift.objects.filter(is_seen=False, created_at__lt=cutoff)
        video_count = video_expired.count()
        video_expired.delete()

        story_expired = StoryGift.objects.filter(is_seen=False, created_at__lt=cutoff)
        story_count = story_expired.count()
        story_expired.delete()

        self.stdout.write(
            self.style.SUCCESS(
                f'Expirados: {user_count} regalos de perfil, {video_count} regalos de video, {story_count} regalos de historia'
            )
        )
