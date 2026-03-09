import os
from cryptography.fernet import Fernet
from django.conf import settings

def get_cipher():
    key = os.getenv('ENCRYPTION_KEY')
    if not key:
        # Fallback for development if not in .env yet, though we added it
        key = Fernet.generate_key()
    return Fernet(key)

def encrypt_data(data: str) -> str:
    if not data:
        return ""
    cipher = get_cipher()
    return cipher.encrypt(data.encode()).decode()

def decrypt_data(encrypted_data: str) -> str:
    if not encrypted_data:
        return ""
    cipher = get_cipher()
    try:
        return cipher.decrypt(encrypted_data.encode()).decode()
    except Exception:
        return "[Error Decrypting]"
