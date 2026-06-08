import os
import sys

from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Buzzy.settings')

# Ensure the project root is in sys.path so task modules are importable
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

app = Celery('Buzzy')
app.config_from_object('django.conf:settings', namespace='CELERY')

# Explicit task modules — autodiscover can miss apps with non-standard layout
app.autodiscover_tasks([
    'apps.ads',
    'apps.videos',
    'apps.recommendations',
    'apps.wallet',
    'apps.users',
    'apps.banners',
])

# Force-import task modules so they register regardless of autodiscover issues
import importlib
for module in [
    'apps.ads.tasks',
    'apps.videos.tasks',
    'apps.recommendations.tasks',
    'apps.wallet.tasks',
    'apps.users.tasks',
    'apps.banners.tasks',
]:
    try:
        importlib.import_module(module)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f'Could not import task module {module}: {e}')
