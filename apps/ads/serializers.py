from rest_framework import serializers
from .models import AdCampaign, AdAudience, AdCreative, AdBudget, AdAnalytics, AdReview


class AdAudienceSerializer(serializers.ModelSerializer):
    class Meta:
        model  = AdAudience
        fields = '__all__'
        read_only_fields = ['campaign']


class AdCreativeSerializer(serializers.ModelSerializer):
    class Meta:
        model  = AdCreative
        fields = '__all__'
        read_only_fields = ['campaign']

    def validate_media_file(self, value):
        if not value:
            return value
        max_size = 100 * 1024 * 1024  # 100 MB
        if value.size > max_size:
            raise serializers.ValidationError("El archivo no puede superar los 100 MB.")
        allowed_types = (
            'image/jpeg', 'image/png', 'image/gif', 'image/webp',
            'video/mp4', 'video/quicktime', 'video/webm',
        )
        content_type = getattr(value, 'content_type', '')
        if content_type not in allowed_types:
            raise serializers.ValidationError(
                "Solo se permiten imágenes (JPEG, PNG, GIF, WEBP) y videos (MP4, MOV, WEBM)."
            )
        return value


class AdBudgetSerializer(serializers.ModelSerializer):
    class Meta:
        model  = AdBudget
        fields = '__all__'
        read_only_fields = ['campaign']


class AdAnalyticsSerializer(serializers.ModelSerializer):
    ctr = serializers.SerializerMethodField()
    cpm = serializers.SerializerMethodField()
    cpc = serializers.SerializerMethodField()

    class Meta:
        model  = AdAnalytics
        fields = ['id', 'campaign', 'date', 'impressions', 'clicks', 'conversions', 'ctr', 'cpm', 'cpc']

    def get_ctr(self, obj):
        return obj.ctr  # property on model

    def get_cpm(self, obj):
        """CPM requires knowing the campaign spend — computed at serializer level."""
        bud = getattr(obj.campaign, 'budget', None)
        if not bud or not obj.impressions:
            return 0.0
        # Daily CPM approximation: (daily spend portion / impressions) * 1000
        # Use global CPM bid as reference
        return float(bud.cpm_bid)

    def get_cpc(self, obj):
        bud = getattr(obj.campaign, 'budget', None)
        if not bud or not obj.clicks:
            return 0.0
        return float(bud.cpc_bid)


class AdReviewSerializer(serializers.ModelSerializer):
    class Meta:
        model  = AdReview
        fields = ['decision', 'rejection_reason', 'submitted_at', 'reviewed_at']


class AdCampaignSerializer(serializers.ModelSerializer):
    audience    = AdAudienceSerializer(required=False)
    creative    = AdCreativeSerializer(required=False)
    budget      = AdBudgetSerializer(required=False)
    analytics   = AdAnalyticsSerializer(many=True, read_only=True)
    review      = AdReviewSerializer(read_only=True)
    total_reach = serializers.SerializerMethodField()
    # Summary metrics for list view
    total_impressions = serializers.SerializerMethodField()
    total_clicks      = serializers.SerializerMethodField()
    ctr               = serializers.SerializerMethodField()
    cpm               = serializers.SerializerMethodField()
    cpc               = serializers.SerializerMethodField()
    spent_pct         = serializers.SerializerMethodField()

    class Meta:
        model  = AdCampaign
        fields = [
            'id', 'user', 'name', 'objective', 'status', 'rejection_reason',
            'start_date', 'end_date', 'created_at', 'updated_at',
            'audience', 'creative', 'budget', 'analytics', 'review',
            'total_reach', 'total_impressions', 'total_clicks',
            'ctr', 'cpm', 'cpc', 'spent_pct',
        ]
        read_only_fields = ['user', 'created_at', 'updated_at']

    def get_total_reach(self, obj):
        from .models import AdImpression
        return AdImpression.objects.filter(campaign=obj).values('user').distinct().count()

    def get_total_impressions(self, obj):
        from django.db.models import Sum
        return obj.analytics.aggregate(s=Sum('impressions'))['s'] or 0

    def get_total_clicks(self, obj):
        from django.db.models import Sum
        return obj.analytics.aggregate(s=Sum('clicks'))['s'] or 0

    def get_ctr(self, obj):
        imp = self.get_total_impressions(obj)
        clk = self.get_total_clicks(obj)
        return round((clk / imp) * 100, 2) if imp else 0.0

    def get_cpm(self, obj):
        bud = getattr(obj, 'budget', None)
        return float(bud.cpm_bid) if bud else 1.43

    def get_cpc(self, obj):
        bud = getattr(obj, 'budget', None)
        return float(bud.cpc_bid) if bud else 0.10

    def get_spent_pct(self, obj):
        bud = getattr(obj, 'budget', None)
        if not bud or not bud.total_budget:
            return 0.0
        return round(float(bud.spent_amount / bud.total_budget) * 100, 2)

    # ── Create ────────────────────────────────
    def create(self, validated_data):
        from django.utils import timezone
        from datetime import timedelta
        from decimal import Decimal

        audience_data = validated_data.pop('audience', None)
        creative_data = validated_data.pop('creative', None)
        budget_data   = validated_data.pop('budget', None)

        # Auto dates
        if not validated_data.get('start_date'):
            validated_data['start_date'] = timezone.now()
        if not validated_data.get('end_date') and budget_data:
            daily = Decimal(str(budget_data.get('daily_budget', 1)))
            total = Decimal(str(budget_data.get('total_budget', daily)))
            days  = max(1, int(total / daily))
            validated_data['end_date'] = validated_data['start_date'] + timedelta(days=days)

        campaign = AdCampaign.objects.create(**validated_data)

        if audience_data and budget_data:
            total_budget = Decimal(str(budget_data.get('total_budget', 0)))
            # Reach estimation based on real platform data (approximated by budget)
            cpm_rate  = Decimal('1.43')
            max_impr  = int((total_budget / cpm_rate) * 1000)
            radius    = audience_data.get('radius', 50)
            has_geo   = audience_data.get('latitude') and audience_data.get('longitude')
            factor    = min(1.0, max(0.1, radius / 50.0)) if has_geo else 1.0
            audience_data['estimated_reach'] = int(max_impr * factor)
            AdAudience.objects.create(campaign=campaign, **audience_data)
        elif audience_data:
            AdAudience.objects.create(campaign=campaign, **audience_data)

        if creative_data:
            AdCreative.objects.create(campaign=campaign, **creative_data)
        if budget_data:
            AdBudget.objects.create(campaign=campaign, **budget_data)

        return campaign
