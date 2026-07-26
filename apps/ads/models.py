from django.db import models
from django.conf import settings


class AdCampaign(models.Model):
    OBJECTIVE_CHOICES = [
        ('TRAFFIC',    'Traffic'),
        ('AWARENESS',  'Awareness'),
        ('SALES',      'Sales'),
        ('FOLLOWERS',  'Followers'),
    ]
    STATUS_CHOICES = [
        ('DRAFT',      'Draft'),
        ('IN_REVIEW',  'In Review'),   # NEW — pending moderation
        ('ACTIVE',     'Active'),
        ('PAUSED',     'Paused'),
        ('REJECTED',   'Rejected'),    # NEW — rejected by moderator
        ('COMPLETED',  'Completed'),
    ]

    user       = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='ad_campaigns')
    name       = models.CharField(max_length=255)
    objective  = models.CharField(max_length=20, choices=OBJECTIVE_CHOICES)
    status     = models.CharField(max_length=20, choices=STATUS_CHOICES, default='DRAFT')
    start_date = models.DateTimeField(null=True, blank=True)
    end_date   = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # ── Boost de contenido propio ──────────────────────────────────
    # Cuando la campaña promociona un video que el usuario ya subió, este FK
    # apunta a ese Video y la campaña NO necesita un AdCreative externo: el
    # video ES el creative. Si es null, la campaña es un anuncio externo
    # clásico (con AdCreative + destination_url). SET_NULL para que borrar el
    # video no destruya el histórico de la campaña/analytics.
    promoted_video = models.ForeignKey(
        'videos.Video',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='promotions',
        help_text="Video propio promocionado (boost). Null = anuncio externo.",
    )

    # Moderation
    rejection_reason = models.TextField(blank=True, default='')

    def __str__(self):
        return self.name

    @property
    def is_boost(self):
        """True si la campaña promociona un video propio en vez de un creative externo."""
        return self.promoted_video_id is not None

    @property
    def is_active(self):
        from django.utils import timezone
        now = timezone.now()
        if self.status != 'ACTIVE':
            return False
        if self.start_date and self.start_date > now:
            return False
        if self.end_date and self.end_date < now:
            return False
        if hasattr(self, 'budget'):
            if self.budget.spent_amount >= self.budget.total_budget:
                return False
        return True


class AdAudience(models.Model):
    GENDER_CHOICES = [
        ('ALL',    'All'),
        ('MALE',   'Male'),
        ('FEMALE', 'Female'),
    ]

    campaign        = models.OneToOneField(AdCampaign, on_delete=models.CASCADE, related_name='audience')
    age_min         = models.PositiveIntegerField(default=18)
    age_max         = models.PositiveIntegerField(default=65)
    gender          = models.CharField(max_length=10, choices=GENDER_CHOICES, default='ALL')
    locations       = models.JSONField(default=list)
    interests       = models.JSONField(default=list)

    # Geolocation
    latitude        = models.FloatField(null=True, blank=True)
    longitude       = models.FloatField(null=True, blank=True)
    radius          = models.PositiveIntegerField(default=50, help_text="Search radius in km")

    estimated_reach = models.PositiveIntegerField(default=0)

    # Frequency cap: max impressions per user per day (0 = unlimited)
    max_frequency   = models.PositiveIntegerField(default=3, help_text="Max times same user sees this ad per day")


class AdCreative(models.Model):
    CTA_CHOICES = [
        ('LEARN_MORE', 'Learn More'),
        ('SHOP_NOW',   'Shop Now'),
        ('SIGN_UP',    'Sign Up'),
        ('CONTACT_US', 'Contact Us'),
        ('WATCH_VIDEO','Watch Video'),
    ]

    # Para boosts de video propio no se crea AdCreative (el video es el creative),
    # por eso los campos admiten vacío: una campaña externa los llena, un boost no.
    campaign        = models.OneToOneField(AdCampaign, on_delete=models.CASCADE, related_name='creative')
    title           = models.CharField(max_length=255, blank=True, default='')
    description     = models.TextField(blank=True, default='')
    media_file      = models.FileField(upload_to='ads/media/', blank=True, null=True)
    cta_text        = models.CharField(max_length=20, choices=CTA_CHOICES, default='LEARN_MORE')
    destination_url = models.URLField(blank=True, default='')


class AdBudget(models.Model):
    BIDDING_CHOICES = [
        ('CPM', 'Cost per 1000 Impressions'),
        ('CPC', 'Cost per Click'),
    ]

    campaign       = models.OneToOneField(AdCampaign, on_delete=models.CASCADE, related_name='budget')
    daily_budget   = models.DecimalField(max_digits=10, decimal_places=2)
    total_budget   = models.DecimalField(max_digits=10, decimal_places=2)
    spent_amount   = models.DecimalField(max_digits=10, decimal_places=4, default=0)

    # Bidding model
    bidding_model  = models.CharField(max_length=10, choices=BIDDING_CHOICES, default='CPM')
    # CPM bid: $ per 1000 impressions (default $1.43 ≈ $0.00143/impression)
    cpm_bid        = models.DecimalField(max_digits=8, decimal_places=4, default='1.4300')
    # CPC bid: $ per click
    cpc_bid        = models.DecimalField(max_digits=8, decimal_places=4, default='0.1000')


class AdAnalytics(models.Model):
    campaign    = models.ForeignKey(AdCampaign, on_delete=models.CASCADE, related_name='analytics')
    impressions = models.PositiveIntegerField(default=0)
    clicks      = models.PositiveIntegerField(default=0)
    conversions = models.PositiveIntegerField(default=0)
    date        = models.DateField(auto_now_add=True)

    class Meta:
        unique_together = ('campaign', 'date')
        verbose_name_plural = "Ad Analytics"

    # Computed metrics (not stored — calculated on the fly)
    @property
    def ctr(self):
        """Click-Through Rate: clicks / impressions × 100"""
        if self.impressions == 0:
            return 0.0
        return round((self.clicks / self.impressions) * 100, 2)

    @property
    def cpm(self):
        """Cost Per Mille: (spent / impressions) × 1000 — needs campaign budget"""
        return None  # Calculated in serializer with campaign spend data

    @property
    def cpc(self):
        """Cost Per Click: spent / clicks — calculated in serializer"""
        return None


class AdImpression(models.Model):
    """Tracks unique impressions per user per campaign (deduplication)."""
    campaign  = models.ForeignKey(AdCampaign, on_delete=models.CASCADE, related_name='campaign_impressions')
    user      = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='ad_impressions')
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('campaign', 'user')
        verbose_name        = "Ad Impression"
        verbose_name_plural = "Ad Impressions"


class AdDailyFrequency(models.Model):
    """Tracks how many times a user has seen an ad today (for frequency capping)."""
    campaign   = models.ForeignKey(AdCampaign, on_delete=models.CASCADE, related_name='daily_frequencies')
    user       = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='ad_daily_frequencies')
    date       = models.DateField()
    view_count = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ('campaign', 'user', 'date')
        verbose_name        = "Ad Daily Frequency"
        verbose_name_plural = "Ad Daily Frequencies"


class AdsConfig(models.Model):
    """Singleton — global config for the ads system (pricing + delivery)."""
    # Pricing
    cpm_rate     = models.DecimalField(max_digits=8, decimal_places=4, default='1.4300',
                                       help_text="$ per 1,000 impressions charged to advertiser")
    cpc_rate     = models.DecimalField(max_digits=8, decimal_places=4, default='0.1000',
                                       help_text="$ per click charged to advertiser")
    ctr_estimate = models.DecimalField(max_digits=5, decimal_places=4, default='0.0200',
                                       help_text="Estimated CTR for reach projections (0.02 = 2%)")

    # Delivery
    ad_every_nth_video = models.PositiveIntegerField(default=3,
                                                     help_text="Show ad every N videos (e.g. 3 = every 3rd video)")
    ad_cooldown_seconds = models.PositiveIntegerField(default=240,
                                                      help_text="Seconds between ads for the same user (default 4min)")
    ads_refresh_seconds = models.PositiveIntegerField(default=300,
                                                      help_text="How often the frontend re-fetches the ad pool (seconds)")

    class Meta:
        verbose_name        = "Ads Config"
        verbose_name_plural = "Ads Config"

    def __str__(self):
        return f"Ads Config — CPM: ${self.cpm_rate} | CPC: ${self.cpc_rate}"

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class AdReview(models.Model):
    """Moderation record for each campaign submitted for review."""
    DECISION_CHOICES = [
        ('PENDING',  'Pending'),
        ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected'),
    ]

    campaign        = models.OneToOneField(AdCampaign, on_delete=models.CASCADE, related_name='review')
    submitted_at    = models.DateTimeField(auto_now_add=True)
    reviewed_at     = models.DateTimeField(null=True, blank=True)
    reviewed_by     = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                        null=True, blank=True, related_name='ad_reviews')
    decision        = models.CharField(max_length=10, choices=DECISION_CHOICES, default='PENDING')
    rejection_reason = models.TextField(blank=True, default='')

    class Meta:
        verbose_name        = "Ad Review"
        verbose_name_plural = "Ad Reviews"

    def __str__(self):
        return f"Review for {self.campaign.name} — {self.decision}"
