from django.db import models
from django.conf import settings

class AdCampaign(models.Model):
    OBJECTIVE_CHOICES = [
        ('TRAFFIC', 'Traffic'),
        ('AWARENESS', 'Awareness'),
        ('SALES', 'Sales'),
        ('FOLLOWERS', 'Followers'),
    ]
    STATUS_CHOICES = [
        ('DRAFT', 'Draft'),
        ('ACTIVE', 'Active'),
        ('PAUSED', 'Paused'),
        ('COMPLETED', 'Completed'),
    ]
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='ad_campaigns')
    name = models.CharField(max_length=255)
    objective = models.CharField(max_length=20, choices=OBJECTIVE_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='DRAFT')
    start_date = models.DateTimeField(null=True, blank=True)
    end_date = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    @property
    def is_active(self):
        from django.utils import timezone
        now = timezone.now()
        
        # Check basic status
        if self.status != 'ACTIVE':
            return False
            
        # Check dates
        if self.start_date and self.start_date > now:
            return False
        if self.end_date and self.end_date < now:
            return False
            
        # Check budget
        if hasattr(self, 'budget'):
            if self.budget.spent_amount >= self.budget.total_budget:
                return False
                
        return True

class AdAudience(models.Model):
    GENDER_CHOICES = [
        ('ALL', 'All'),
        ('MALE', 'Male'),
        ('FEMALE', 'Female'),
    ]
    campaign = models.OneToOneField(AdCampaign, on_delete=models.CASCADE, related_name='audience')
    age_min = models.PositiveIntegerField(default=18)
    age_max = models.PositiveIntegerField(default=65)
    gender = models.CharField(max_length=10, choices=GENDER_CHOICES, default='ALL')
    locations = models.JSONField(default=list)
    interests = models.JSONField(default=list)
    
    # Geolocation fields
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    radius = models.PositiveIntegerField(default=50, help_text="Search radius in kilometers")
    
    estimated_reach = models.PositiveIntegerField(default=0)

class AdCreative(models.Model):
    CTA_CHOICES = [
        ('LEARN_MORE', 'Learn More'),
        ('SHOP_NOW', 'Shop Now'),
        ('SIGN_UP', 'Sign Up'),
        ('CONTACT_US', 'Contact Us'),
        ('WATCH_VIDEO', 'Watch Video'),
    ]
    campaign = models.OneToOneField(AdCampaign, on_delete=models.CASCADE, related_name='creative')
    title = models.CharField(max_length=255)
    description = models.TextField()
    media_file = models.FileField(upload_to='ads/media/')
    cta_text = models.CharField(max_length=20, choices=CTA_CHOICES, default='LEARN_MORE')
    destination_url = models.URLField()

class AdBudget(models.Model):
    campaign = models.OneToOneField(AdCampaign, on_delete=models.CASCADE, related_name='budget')
    daily_budget = models.DecimalField(max_digits=10, decimal_places=2)
    total_budget = models.DecimalField(max_digits=10, decimal_places=2)
    spent_amount = models.DecimalField(max_digits=10, decimal_places=4, default=0)

class AdAnalytics(models.Model):
    campaign = models.ForeignKey(AdCampaign, on_delete=models.CASCADE, related_name='analytics')
    impressions = models.PositiveIntegerField(default=0)
    clicks = models.PositiveIntegerField(default=0)
    conversions = models.PositiveIntegerField(default=0)
    date = models.DateField(auto_now_add=True)

    class Meta:
        unique_together = ('campaign', 'date')
        verbose_name_plural = "Ad Analytics"

class AdImpression(models.Model):
    campaign = models.ForeignKey(AdCampaign, on_delete=models.CASCADE, related_name='campaign_impressions')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='ad_impressions')
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('campaign', 'user')
        verbose_name = "Ad Impression"
        verbose_name_plural = "Ad Impressions"
