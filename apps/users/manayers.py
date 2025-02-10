from django.contrib.auth.models import BaseUserManager

class CustomUserManager(BaseUserManager):
    def _create_user(self, email, username, password=None, is_staff=False, is_superuser=False, **extra_fields):
        """
        Helper function for creating both regular users and superusers.
        """
        if not email:
            raise ValueError('The Email field must be set')
        
        email = self.normalize_email(email)  # Normalize the email address.
        user = self.model(email=email, username=username, is_staff=is_staff, is_superuser=is_superuser, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user
    
    def create_user(self, email, username, password=None, **extra_fields):
        """
        Create and return a regular user with an email and password.
        """
        return self._create_user(email, username, password, is_staff=False, is_superuser=False, **extra_fields)
    
    def create_superuser(self, email, username, password=None, **extra_fields):
        """
        Create and return a superuser with an email, password, and the necessary permissions.
        """
        return self._create_user(email, username, password, is_staff=True, is_superuser=True, **extra_fields)
    
    def active_users(self):
        return self.filter(is_active=True)
    
    def recent_users(self):
        return self.order_by('-date_joined')[:5]
