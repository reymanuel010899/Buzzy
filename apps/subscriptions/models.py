from django.db import models
from apps.users.models import User

class SubscriptionPlan(models.Model):
    NAME_CHOICES = [
        ('VIP', 'VIP'),
        ('PLUS', 'Plus'),
        ('FRIEND', 'Friend'),
    ]

    name = models.CharField(max_length=20, choices=NAME_CHOICES, unique=True)
    description = models.TextField(blank=True, null=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    stripe_price_id = models.CharField(max_length=100, blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

class UserSubscription(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='subscription')
    plan = models.ForeignKey(SubscriptionPlan, on_delete=models.SET_NULL, null=True, blank=True)
    stripe_subscription_id = models.CharField(max_length=100, blank=True, null=True)
    stripe_customer_id = models.CharField(max_length=100, blank=True, null=True)
    start_date = models.DateTimeField(auto_now_add=True)
    end_date = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=False)
    
    # Tracking perks (optional but good for limits)
    comments_this_month = models.PositiveIntegerField(default=0)
    calls_this_month = models.PositiveIntegerField(default=0)
    last_reset_date = models.DateField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} - {self.plan.name if self.plan else 'No Plan'}"

    @property
    def is_premium(self):
        return self.is_active and self.plan is not None

    def reset_if_new_month(self):
        from django.utils import timezone
        now = timezone.now().date()
        if self.last_reset_date.month != now.month or self.last_reset_date.year != now.year:
            self.comments_this_month = 0
            self.calls_this_month = 0
            self.last_reset_date = now
            self.save()

    def can_make_call(self):
        self.reset_if_new_month()
        if not self.is_active or not self.plan:
            return False, "Necesitas una suscripción activa."
        
        limit = 0
        if self.plan.name == 'PLUS':
            limit = 3
        elif self.plan.name == 'FRIEND':
            limit = 5
        
        if limit == 0:
            return False, "Tu plan no incluye llamadas."
        
        if self.calls_this_month >= limit:
            return False, f"Has alcanzado tu límite de {limit} llamadas este mes."
        
        return True, "Ok"

    def can_post_comment(self):
        self.reset_if_new_month()
        if self.plan and self.plan.name == 'VIP':
            if self.comments_this_month >= 30:
                return False, "Has alcanzado tu límite de 30 comentarios VIP."
        return True, "Ok"
