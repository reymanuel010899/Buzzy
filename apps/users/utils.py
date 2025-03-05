import random
import string
from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone
from datetime import timedelta

def generate_reset_code(length=6):
    """Genera un código numérico de 6 dígitos."""
    return ''.join(random.choices(string.digits, k=length))

def send_recovery_email(email, code):
    subject = 'Código de recuperación de contraseña - Buzzy'
    message = f'Tu código de recuperación es: {code}. Este código expirará en 10 minutos.'
    
    # Usa directamente el usuario de Gmail configurado
    email_from = settings.EMAIL_HOST_USER 
    print(email_from)
    try:
        send_mail(subject, message, email_from, [email], fail_silently=False)
        return True
    except Exception as e:
        print(f"Error enviando email: {e}")
        return False
