"""
python manage.py seed_premium_gifts
Creates the exclusive Buzzy Premium gifts (no video file required — emoji only).
"""
from django.core.management.base import BaseCommand
from apps.videos.models import GiftStory


PREMIUM_GIFTS = [
    {'name': 'Corona de Oro',    'slug': 'corona-de-oro',    'emoji': '👑', 'token_price': 500,  'color': '#FFD700'},
    {'name': 'Diamante',         'slug': 'diamante',          'emoji': '💎', 'token_price': 1000, 'color': '#B9F2FF'},
    {'name': 'Cohete Premium',   'slug': 'cohete-premium',    'emoji': '🚀', 'token_price': 750,  'color': '#A855F7'},
    {'name': 'Estrella Buzzy',   'slug': 'estrella-buzzy',   'emoji': '⭐', 'token_price': 300,  'color': '#FACC15'},
    {'name': 'Fuego Premium',    'slug': 'fuego-premium',     'emoji': '🔥', 'token_price': 200,  'color': '#F97316'},
    {'name': 'Trofeo',           'slug': 'trofeo',            'emoji': '🏆', 'token_price': 2000, 'color': '#EAB308'},
    {'name': 'Corazón Premium',  'slug': 'corazon-premium',  'emoji': '💜', 'token_price': 150,  'color': '#9333EA'},
    {'name': 'Universo',         'slug': 'universo',          'emoji': '🌌', 'token_price': 5000, 'color': '#6366F1'},
]


class Command(BaseCommand):
    help = 'Seed exclusive Buzzy Premium gifts'

    def handle(self, *args, **kwargs):
        created = 0
        for g in PREMIUM_GIFTS:
            obj, was_created = GiftStory.objects.update_or_create(
                slug=g['slug'],
                defaults={
                    'name': g['name'],
                    'emoji': g['emoji'],
                    'token_price': g['token_price'],
                    'color_premiun': g['color'],
                    'is_premium_exclusive': True,
                    'is_active': True,
                    'video': '',  # no video file — emoji only
                }
            )
            if was_created:
                created += 1
                self.stdout.write(self.style.SUCCESS(f'  ✓ Creado: {obj.name}'))
            else:
                self.stdout.write(f'  ~ Ya existe: {obj.name}')

        self.stdout.write(self.style.SUCCESS(f'\n{created} regalos Premium creados.'))
