"""Campos de modelo con cifrado transparente (Fernet/AES).

Se usan para guardar secretos (tokens OAuth de redes sociales) cifrados en la BD.
El valor se cifra al guardar y se descifra al leer, de forma transparente: el resto
del código sigue usando `obj.access_token` como un string normal.

Requiere la env var FIELD_ENCRYPTION_KEY (una clave Fernet base64). Generar una con:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""
import os

from cryptography.fernet import Fernet, InvalidToken
from django.core.exceptions import ImproperlyConfigured
from django.db import models

# Prefijo que marca un valor ya cifrado por este módulo. Permite distinguir
# texto en claro (datos legacy) de ciphertext sin intentar descifrar a ciegas.
_PREFIX = "enc::"


def _get_fernet():
    key = os.getenv("FIELD_ENCRYPTION_KEY")
    if not key:
        raise ImproperlyConfigured(
            "FIELD_ENCRYPTION_KEY environment variable is required to "
            "encrypt/decrypt sensitive fields."
        )
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except Exception as exc:  # clave malformada
        raise ImproperlyConfigured(f"FIELD_ENCRYPTION_KEY is invalid: {exc}")


class EncryptedTextField(models.TextField):
    """TextField que cifra su contenido en la base de datos.

    - Al GUARDAR: cifra el valor y lo almacena como 'enc::<ciphertext>'.
    - Al LEER: descifra y devuelve el texto en claro.
    - Valores vacíos/None se guardan tal cual (no se cifran).
    - Valores legacy sin el prefijo se devuelven sin tocar (compatibilidad).
    """

    def get_prep_value(self, value):
        if value is None or value == "":
            return value
        if isinstance(value, str) and value.startswith(_PREFIX):
            return value  # ya cifrado (evita doble cifrado)
        token = _get_fernet().encrypt(str(value).encode()).decode()
        return f"{_PREFIX}{token}"

    def from_db_value(self, value, expression, connection):
        return self._decrypt(value)

    def to_python(self, value):
        # Llamado en validación/deserialización; descifra si aplica.
        if isinstance(value, str) and value.startswith(_PREFIX):
            return self._decrypt(value)
        return value

    @staticmethod
    def _decrypt(value):
        if value is None or value == "":
            return value
        if not (isinstance(value, str) and value.startswith(_PREFIX)):
            return value  # legacy en claro: devolver tal cual
        ciphertext = value[len(_PREFIX):]
        try:
            return _get_fernet().decrypt(ciphertext.encode()).decode()
        except InvalidToken:
            # Clave equivocada o dato corrupto: no romper la app, devolver vacío.
            return ""
