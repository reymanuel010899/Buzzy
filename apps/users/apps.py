import os
import firebase_admin
from firebase_admin import credentials
from django.apps import AppConfig
from django.conf import settings

class UsersConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.users'
    
    def ready(self):
        import apps.users.signals  # noqa: F401  ← Esto activa la señal
        if os.environ.get('RUN_MAIN') == 'true' or not settings.DEBUG:
            service_account_path = getattr(settings, "FIREBASE_SERVICE_ACCOUNT_PATH", None)
            if service_account_path and os.path.exists(service_account_path):
                if not firebase_admin._apps:
                    cred = credentials.Certificate(service_account_path)
                    firebase_admin.initialize_app(cred)