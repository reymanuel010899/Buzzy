import uuid
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

class SubscriptionBenefit(models.Model):
    BENEFIT_TYPES = [
        ('CALLS', 'Llamadas Mensuales'),
        ('VIDEO CALLS', 'Videos Llamadas Mensuales'),
        ('MESSAGES', 'Mensages Mensuales'),
        ('COMMENTS', 'Comentarios VIP'),
        ('DESIGNS', 'Nuevo Design Interface'),
        ('AI_GENERATION', 'Generación de Videos/Imágenes con IA'),
        ('OTHER', 'Otros beneficios'),
    ]
    
    plan = models.ForeignKey(SubscriptionPlan, on_delete=models.CASCADE, related_name='benefits')
    benefit_type = models.CharField(max_length=20, choices=BENEFIT_TYPES)
    limit = models.PositiveIntegerField(help_text="0 para ilimitado, o un número específico")
    description = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        verbose_name='Beneficio de suscripcion'
        #unique_together = ('plan', 'benefit_type')

    def __str__(self):
        return f"{self.plan.name} - {self.get_benefit_type_display()}: {self.limit}"

class UserSubscription(models.Model):
    subscriber = models.ForeignKey(User, on_delete=models.CASCADE, related_name='subscriptions_made', null=True, blank=True)
    subscribed_to = models.ForeignKey(User, on_delete=models.CASCADE, related_name='subscriptions_received', null=True, blank=True)
    plan = models.ForeignKey(SubscriptionPlan, on_delete=models.SET_NULL, null=True, blank=True)
    stripe_subscription_id = models.CharField(max_length=100, blank=True, null=True)
    stripe_customer_id = models.CharField(max_length=100, blank=True, null=True)

    class Meta:
        unique_together = ('subscriber', 'subscribed_to')
    start_date = models.DateTimeField(auto_now_add=True)
    end_date = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=False)
    
    # Tracking perks (optional but good for limits)
    comments_this_month = models.PositiveIntegerField(default=0)
    calls_this_month = models.PositiveIntegerField(default=0)
    video_calls_this_month = models.PositiveIntegerField(default=0)
    voice_seconds_this_month = models.PositiveIntegerField(default=0)
    video_seconds_consumed_this_month = models.PositiveIntegerField(default=0)
    ai_generations_this_month = models.PositiveIntegerField(default=0)
    last_reset_date = models.DateField(auto_now_add=True)

    def activate(self, plan, stripe_subscription_id=None, stripe_customer_id=None):
        """
        Activates or updates the subscription and resets usage metrics.
        """
        self.plan = plan
        if stripe_subscription_id:
            self.stripe_subscription_id = stripe_subscription_id
        if stripe_customer_id:
            self.stripe_customer_id = stripe_customer_id
        
        # Reset usage metrics on plan update/activation
        self.comments_this_month = 0
        self.calls_this_month = 0
        self.video_calls_this_month = 0
        self.voice_seconds_this_month = 0
        self.video_seconds_consumed_this_month = 0
        self.ai_generations_this_month = 0
        from django.utils import timezone
        self.last_reset_date = timezone.now().date()
        
        self.is_active = True
        self.save()

    def __str__(self):
        return f"{self.subscriber.username} -> {self.subscribed_to.username}: {self.plan.name if self.plan else 'No Plan'}"

    @property
    def is_premium(self):
        return self.is_active and self.plan is not None

    def reset_if_new_month(self):
        from django.utils import timezone
        now = timezone.now().date()
        if self.last_reset_date.month != now.month or self.last_reset_date.year != now.year:
            self.comments_this_month = 0
            self.calls_this_month = 0
            self.video_calls_this_month = 0
            self.voice_seconds_this_month = 0
            self.video_seconds_consumed_this_month = 0
            self.ai_generations_this_month = 0
            self.last_reset_date = now
            self.save()

    def get_benefit_limit(self, benefit_type):
        if not self.plan:
            return 0
        benefit = SubscriptionBenefit.objects.filter(plan=self.plan, benefit_type=benefit_type).first()
        return benefit.limit if benefit else 0

    def get_remaining_seconds(self, benefit_type):
        self.reset_if_new_month()
        limit_minutes = self.get_benefit_limit(benefit_type)
        if limit_minutes <= 0:
            return 0
        used_seconds = self.video_seconds_consumed_this_month if benefit_type == 'VIDEO CALLS' else self.voice_seconds_this_month
        return max(0, (limit_minutes * 60) - used_seconds)

    def consume_call_seconds(self, seconds, call_type):
        self.reset_if_new_month()
        seconds = max(0, int(seconds))
        if call_type == 'video':
            self.video_seconds_consumed_this_month += seconds
            if seconds > 0:
                self.video_calls_this_month += 1
        else:
            self.voice_seconds_this_month += seconds
            if seconds > 0:
                self.calls_this_month += 1
        self.save(update_fields=[
            'video_seconds_consumed_this_month',
            'voice_seconds_this_month',
            'video_calls_this_month',
            'calls_this_month',
            'last_reset_date',
        ])

    def can_make_call(self):
        self.reset_if_new_month()
        if not self.is_active or not self.plan:
            return False, "Necesitas una suscripción activa."
        
        limit = self.get_benefit_limit('CALLS')
        
        if limit == 0:
            return False, "Tu plan no incluye llamadas."
        
        remaining_seconds = self.get_remaining_seconds('CALLS')
        if remaining_seconds <= 0:
            return False, f"Has alcanzado tu límite de {limit} minutos de llamadas este mes."

        return True, "Ok"

    def can_make_video_call(self):
        self.reset_if_new_month()
        if not self.is_active or not self.plan:
            return False, "Necesitas una suscripción activa."

        limit = self.get_benefit_limit('VIDEO CALLS')

        if limit == 0:
            return False, "Tu plan no incluye videollamadas."

        remaining_seconds = self.get_remaining_seconds('VIDEO CALLS')
        if remaining_seconds <= 0:
            return False, f"Has alcanzado tu límite de {limit} minutos de videollamadas este mes."

        return True, "Ok"

    def can_generate_ai(self):
        self.reset_if_new_month()
        if not self.is_active or not self.plan:
            return False, "Necesitas una suscripción activa para usar la IA."
            
        limit = self.get_benefit_limit('AI_GENERATION')

        if limit == 0:
            return False, "Tu plan no incluye generación con IA."
            
        if self.ai_generations_this_month >= limit:
            return False, f"Has alcanzado tu límite de {limit} generaciones con IA este mes."
        
        return True, "Ok"

    def can_post_comment(self):
        self.reset_if_new_month()
        if not self.is_active or not self.plan:
            return False, "Necesitas una suscripción activa."

        limit = self.get_benefit_limit('COMMENTS')
        print(limit)
        if limit == 0:
            return False, "Tu plan no incluye comentarios destacados."

        if self.comments_this_month >= limit:
            return False, f"Has alcanzado tu límite de {limit} comentarios destacados este mes."

        return True, "Ok"


class CallSession(models.Model):
    CALL_TYPE_CHOICES = [
        ('voice', 'Voice'),
        ('video', 'Video'),
    ]

    STATUS_CHOICES = [
        ('initiated', 'Initiated'),
        ('ringing', 'Ringing'),
        ('active', 'Active'),
        ('ended', 'Ended'),
        ('expired', 'Expired'),
        ('missed', 'Missed'),
        ('rejected', 'Rejected'),
        ('failed', 'Failed'),
    ]

    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    caller = models.ForeignKey(User, on_delete=models.CASCADE, related_name='calls_started')
    callee = models.ForeignKey(User, on_delete=models.CASCADE, related_name='calls_received')
    subscription = models.ForeignKey(UserSubscription, on_delete=models.CASCADE, related_name='call_sessions')
    call_type = models.CharField(max_length=10, choices=CALL_TYPE_CHOICES)
    channel_name = models.CharField(max_length=255, unique=True)
    agora_uid_caller = models.PositiveIntegerField()
    agora_uid_callee = models.PositiveIntegerField()
    allowed_seconds = models.PositiveIntegerField(default=0)
    consumed_seconds = models.PositiveIntegerField(default=0)
    started_at = models.DateTimeField(auto_now_add=True)
    answered_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='initiated')
    ended_reason = models.CharField(max_length=50, blank=True, null=True)
    agora_token_expire_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['-started_at']

    def __str__(self):
        return f"{self.call_type} {self.caller.username} -> {self.callee.username} ({self.status})"
