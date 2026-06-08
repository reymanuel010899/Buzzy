import os
import subprocess
import tempfile
from django.core.management.base import BaseCommand
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from apps.videos.models import GiftStory


class Command(BaseCommand):
    help = "Generate thumbnails for all GiftStory objects that have a video but no thumbnail"

    def handle(self, *args, **options):
        gifts = GiftStory.objects.filter(video__isnull=False).exclude(video='')
        total = gifts.count()
        done = 0
        skipped = 0

        for gift in gifts:
            if gift.thumbnail:
                skipped += 1
                continue
            try:
                video_path = gift.video.path
                with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp:
                    tmp_path = tmp.name

                result = subprocess.run(
                    ['ffmpeg', '-y', '-i', video_path, '-vframes', '1', '-q:v', '2', tmp_path],
                    capture_output=True, timeout=30
                )

                if result.returncode == 0:
                    with open(tmp_path, 'rb') as f:
                        thumb_name = f'gifts/thumbnails/{gift.slug}.jpg'
                        saved_path = default_storage.save(thumb_name, ContentFile(f.read()))
                        GiftStory.objects.filter(pk=gift.pk).update(thumbnail=saved_path)
                    done += 1
                    self.stdout.write(f'  ✓ {gift.slug}')
                else:
                    self.stdout.write(self.style.WARNING(f'  ✗ {gift.slug}: ffmpeg error'))

                os.unlink(tmp_path)
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'  ✗ {gift.slug}: {e}'))

        self.stdout.write(self.style.SUCCESS(
            f'\nDone: {done} generated, {skipped} already had thumbnail, {total - done - skipped} failed'
        ))
