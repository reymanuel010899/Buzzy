from rest_framework import serializers
from .models import AdCampaign, AdAudience, AdCreative, AdBudget, AdAnalytics

class AdAudienceSerializer(serializers.ModelSerializer):
    class Meta:
        model = AdAudience
        fields = '__all__'
        read_only_fields = ['campaign']

class AdCreativeSerializer(serializers.ModelSerializer):
    class Meta:
        model = AdCreative
        fields = '__all__'
        read_only_fields = ['campaign']

class AdBudgetSerializer(serializers.ModelSerializer):
    class Meta:
        model = AdBudget
        fields = '__all__'
        read_only_fields = ['campaign']

class AdAnalyticsSerializer(serializers.ModelSerializer):
    class Meta:
        model = AdAnalytics
        fields = '__all__'

class AdCampaignSerializer(serializers.ModelSerializer):
    audience = AdAudienceSerializer(required=False)
    creative = AdCreativeSerializer(required=False)
    budget = AdBudgetSerializer(required=False)
    analytics = AdAnalyticsSerializer(many=True, read_only=True)
    total_reach = serializers.SerializerMethodField()

    class Meta:
        model = AdCampaign
        fields = ['id', 'user', 'name', 'objective', 'status', 'start_date', 'end_date', 'created_at', 'updated_at', 'audience', 'creative', 'budget', 'analytics', 'total_reach']
        read_only_fields = ['user', 'created_at', 'updated_at']

    def get_total_reach(self, obj):
        from .models import AdImpression
        return AdImpression.objects.filter(campaign=obj).values('user').distinct().count()

    def create(self, validated_data):
        from django.utils import timezone
        from datetime import timedelta
        from decimal import Decimal
        
        audience_data = validated_data.pop('audience', None)
        creative_data = validated_data.pop('creative', None)
        budget_data = validated_data.pop('budget', None)
        
        # Calculate dates if not provided
        if not validated_data.get('start_date'):
            validated_data['start_date'] = timezone.now()
            
        if not validated_data.get('end_date') and budget_data:
            daily = Decimal(budget_data.get('daily_budget', 1))
            total = Decimal(budget_data.get('total_budget', daily))
            days = int(total / daily)
            validated_data['end_date'] = validated_data['start_date'] + timedelta(days=days)
            
        campaign = AdCampaign.objects.create(**validated_data)
        
        if audience_data:
            # Estimate reach with "Carinito" (Bonus for higher budget)
            if budget_data:
                total_budget = Decimal(budget_data.get('total_budget', 0))
                # Base is 700. Add 10 per each $10 spent as a bonus.
                rate = 700 + (int(total_budget) // 10) * 10
                base_reach = int(total_budget * Decimal(str(rate)))
                
                # Apply radius factor if geolocation is used
                radius = audience_data.get('radius')
                has_coords = audience_data.get('latitude') and audience_data.get('longitude')
                
                if has_coords and radius:
                    # Simulation: smaller radius = lower reach
                    # 50km is standard (1.0x). 10km is 0.2x. 100km+ is 1.0x.
                    factor = min(1.0, max(0.1, radius / 50.0))
                    audience_data['estimated_reach'] = int(base_reach * factor)
                else:
                    audience_data['estimated_reach'] = base_reach
            
            AdAudience.objects.create(campaign=campaign, **audience_data)
            
        if creative_data:
            AdCreative.objects.create(campaign=campaign, **creative_data)
        if budget_data:
            AdBudget.objects.create(campaign=campaign, **budget_data)
            
        return campaign
