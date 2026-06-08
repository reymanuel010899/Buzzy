"""Temporary settings override to point Django at the SQLite DB for dumpdata."""
from Buzzy.settings import *  # noqa

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}
