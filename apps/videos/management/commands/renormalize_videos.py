"""
Re-normalize existing feed videos to the standard format (720x1280, H.264,
+faststart) and regenerate their thumbnails from the opening frame.

Run once after deploying the normalization pipeline so old uploads (e.g. the
200x200 square clips) match the new smooth, consistent feed.

Usage:
    python manage.py renormalize_videos              # all videos
    python manage.py renormalize_videos --limit 50   # first 50 only
    python manage.py renormalize_videos --only-small # only sub-standard sizes
    python manage.py renormalize_videos --dry-run    # report, change nothing
"""

import os

from django.core.management.base import BaseCommand

from apps.videos.models import Video
from apps.videos.tasks import (
    NORMALIZE_HEIGHT,
    NORMALIZE_WIDTH,
    _probe_video_stream,
    generate_thumbnail,
    normalize_video,
)


class Command(BaseCommand):
    help = "Re-normalize existing videos to 720x1280 and regenerate thumbnails."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=0,
                            help="Process at most N videos (0 = all).")
        parser.add_argument("--only-small", action="store_true",
                            help="Only videos whose dimensions differ from the target.")
        parser.add_argument("--dry-run", action="store_true",
                            help="Report what would be done without changing files.")
        parser.add_argument("--regen-thumb", action="store_true", default=True,
                            help="Regenerate the thumbnail after normalizing (default on).")

    def handle(self, *args, **opts):
        qs = Video.objects.exclude(video="").order_by("id")
        total = qs.count()
        self.stdout.write(f"Found {total} videos with a file.")

        processed = ok = skipped = failed = 0

        for video in qs.iterator():
            if opts["limit"] and processed >= opts["limit"]:
                break

            try:
                path = video.video.path
            except Exception:
                skipped += 1
                continue

            if not path or not os.path.exists(path):
                self.stdout.write(self.style.WARNING(f"  [{video.id}] file missing — skip"))
                skipped += 1
                continue

            info = _probe_video_stream(path)
            # "Standard" means more than the right box + codec: the profile must be
            # hardware-friendly (NOT High) and the fps sane. A 720x1280 h264 clip
            # that is High@1000fps is exactly what tiles on Android, so it must NOT
            # be treated as already-standard or it'd be skipped under --only-small.
            mobile_safe_profile = info["profile"] in (
                "baseline", "constrained baseline", "main",
            )
            sane_fps = 0 < info["fps"] <= 31
            already_standard = (info["width"] == NORMALIZE_WIDTH and
                                info["height"] == NORMALIZE_HEIGHT and
                                info["codec"] == "h264" and
                                mobile_safe_profile and
                                sane_fps)

            if opts["only_small"] and already_standard:
                skipped += 1
                continue

            processed += 1
            label = (f"[{video.id}] {info['width']}x{info['height']} {info['codec']} "
                     f"{info['profile'] or '?'} {info['fps']:.0f}fps")

            if opts["dry_run"]:
                action = "already standard" if already_standard else "WOULD normalize"
                self.stdout.write(f"  {label} -> {action}")
                continue

            if normalize_video(path):
                ok += 1
                msg = f"  {label} -> normalized OK"
                if opts["regen_thumb"]:
                    new_thumb = generate_thumbnail(path, str(video.uuid))
                    if new_thumb:
                        video.thumbnail_url = new_thumb
                        video.save(update_fields=["thumbnail_url"])
                        msg += " + thumbnail"
                self.stdout.write(self.style.SUCCESS(msg))
            else:
                failed += 1
                self.stdout.write(self.style.ERROR(f"  {label} -> normalize FAILED (left untouched)"))

        self.stdout.write(self.style.SUCCESS(
            f"\nDone. processed={processed} ok={ok} failed={failed} skipped={skipped}"
        ))
