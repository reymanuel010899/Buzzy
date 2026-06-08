from django.core.management.base import BaseCommand
from apps.banners.sync import sync_all_groups


class Command(BaseCommand):
    help = 'Sincroniza membresías automáticas de grupos de usuarios'

    def add_arguments(self, parser):
        parser.add_argument('--group', type=int, help='ID de grupo específico a sincronizar')

    def handle(self, *args, **options):
        group_id = options.get('group')
        self.stdout.write('Sincronizando grupos...')
        added, removed = sync_all_groups(group_id=group_id)
        self.stdout.write(self.style.SUCCESS(
            f'✅ Sincronización completa: {added} añadidos, {removed} removidos.'
        ))
