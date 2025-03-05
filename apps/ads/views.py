import random
import math
import json
from django.db.models import Sum, Count
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import AdCampaign, AdAnalytics
from django.conf import settings
from .serializers import AdCampaignSerializer, AdAnalyticsSerializer
from apps.ads.models import AdImpression

def haversine_distance(lat1, lon1, lat2, lon2):
    R = 6371.0  # Earth radius in km
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

class AdCampaignViewSet(viewsets.ModelViewSet):
    serializer_class = AdCampaignSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        if self.action in ['track_impression', 'track_click', 'serve']:
            return AdCampaign.objects.all()
        return AdCampaign.objects.filter(user=self.request.user)

    def create(self, request, *args, **kwargs):
        # Handle flattened nested data from FormData (e.g. audience.age_min)
        nested_data = {}
        
        # Iterate over request.data directly to avoid errors with copying files
        for key, value in request.data.items():
            if '.' in key:
                parts = key.split('.')
                parent = parts[0]
                child = parts[1]
                if parent not in nested_data:
                    nested_data[parent] = {}
                
                # Special handling for JSON fields sent as strings
                if child in ['locations', 'interests']:
                    try:
                        nested_data[parent][child] = json.loads(value)
                    except:
                        nested_data[parent][child] = value
                else:
                    nested_data[parent][child] = value
            else:
                nested_data[key] = value

        serializer = self.get_serializer(data=nested_data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    @action(detail=False, methods=['get'])
    def serve(self, request):
        from django.utils import timezone
        today = timezone.now().date()
        
        # Logic to serve ads to users
        # Filter campaigns that are is_active and haven't reached their daily limit
        active_campaigns = []
        for campaign in AdCampaign.objects.all():
            if not campaign.is_active:
                continue
                
            # Reach target logic: (Total Reach / Duration) or (Daily Budget * 700)
            if hasattr(campaign, 'budget') and hasattr(campaign, 'audience'):
                # 1. Check Proximity if user location is provided
                lat = request.query_params.get('lat')
                lng = request.query_params.get('lng')
                
                if lat and lng and campaign.audience.latitude and campaign.audience.longitude:
                    try:
                        u_lat, u_lng = float(lat), float(lng)
                        a_lat, a_lng = float(campaign.audience.latitude), float(campaign.audience.longitude)
                        distance = haversine_distance(u_lat, u_lng, a_lat, a_lng)
                        
                        if distance > campaign.audience.radius:
                            # Too far away
                            continue
                    except (ValueError, TypeError):
                        pass

                # 1.1 Check Country Match
                # Si el anuncio tiene ubicaciones definidas y el usuario tiene país, 
                # el país del usuario debe estar contenido en alguna de esas ubicaciones para que lo vea.
                user_country = getattr(request.user, 'country', None)
                if user_country and hasattr(campaign.audience, 'locations'):
                    locations = campaign.audience.locations
                    if isinstance(locations, list) and len(locations) > 0:
                        # Si es un array de textos, chequear que el pais del usuario esté en alguno de los textos
                        country_match = any(user_country.name.lower() in loc.lower() for loc in locations)
                        if not country_match:
                            continue

                daily_target = campaign.budget.daily_budget * 700
                
                # Get today's impressions
                analytics = AdAnalytics.objects.filter(campaign=campaign, date=today).first()
                today_impressions = analytics.impressions if analytics else 0
                
                if today_impressions < daily_target:
                    active_campaigns.append(campaign)
            else:
                active_campaigns.append(campaign)
        
        # Shuffle to provide variety
        random.shuffle(active_campaigns)
        
        # Limit results
        if len(active_campaigns) > 5:
            active_campaigns = random.sample(active_campaigns, 5)
            
        serializer = self.get_serializer(active_campaigns, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def track_impression(self, request, pk=None):
        campaign = self.get_object()
        user = request.user
        
        # Check if this user has already seen this campaign
        impression_exists = AdImpression.objects.filter(campaign=campaign, user=user).exists()
        
        if impression_exists:
            return Response({'status': 'already_tracked'})

        # Record unique impression
        AdImpression.objects.create(campaign=campaign, user=user)
        from django.utils import timezone
        today = timezone.now().date()
        
        analytics, created = AdAnalytics.objects.get_or_create(
            campaign=campaign, 
            date=today
        )
        analytics.impressions += 1
        analytics.save()
        
        # Deduct from budget (Simulation: $1 per 700 people => ~$0.0014 per impression)
        if hasattr(campaign, 'budget'):
            from decimal import Decimal
            # We use a slightly more precise value to match $1 = 700 reach
            cost = Decimal('0.00143') 
            campaign.budget.spent_amount += cost
            campaign.budget.save()
            
            # Auto-pause if budget exhausted
            if campaign.budget.spent_amount >= campaign.budget.total_budget:
                campaign.status = 'COMPLETED'
                campaign.save()
                
        return Response({'status': 'tracked'})

    @action(detail=False, methods=['get'])
    def dashboard_stats(self, request):
        
        # Consider active and draft campaigns for the dashboard summary
        user_campaigns = AdCampaign.objects.filter(user=request.user)
        active_campaign_ids = user_campaigns.filter(status='ACTIVE').values_list('id', flat=True)
        draft_campaign_ids = user_campaigns.filter(status='DRAFT').values_list('id', flat=True)
        
        # 1. Total Reach: Unique users who saw any of my ACTIVE campaigns
        total_reach = AdImpression.objects.filter(campaign_id__in=active_campaign_ids).values('user').distinct().count()
        
        # 2. Total Impressions & Interacciones (Clicks/Interactions)
        analytics_summary = AdAnalytics.objects.filter(campaign_id__in=active_campaign_ids).aggregate(
            total_impressions=Sum('impressions'),
            total_clicks=Sum('clicks')
        )
 
        # 3. Total Spent
        total_spent = 0
        active_count = len(active_campaign_ids)

        
        for campaign in AdCampaign.objects.filter(id__in=active_campaign_ids):
            if hasattr(campaign, 'budget'):
                total_spent += campaign.budget.spent_amount

               
        return Response({
            'total_reach': total_reach,
            'total_impressions': analytics_summary['total_impressions'] or 0,
            'total_interactions': analytics_summary['total_clicks'] or 0,
            'total_spent': float(total_spent),
            'active_campaigns': len(active_campaign_ids),
            'draft_campaigns': len(draft_campaign_ids)
        })

    @action(detail=True, methods=['post'])
    def relaunch(self, request, pk=None):
        campaign = self.get_object()
        from django.utils import timezone
        from datetime import timedelta
        from decimal import Decimal
        
        if campaign.status in ['COMPLETED', 'PAUSED']:
             # Reset budget spent and update dates
             if hasattr(campaign, 'budget'):
                 campaign.budget.spent_amount = Decimal('0.00')
                 campaign.budget.save()
                 
                 # Recalculate duration
                 daily = campaign.budget.daily_budget
                 total = campaign.budget.total_budget
                 days = int(total / daily)
                 
                 campaign.start_date = timezone.now()
                 campaign.end_date = campaign.start_date + timedelta(days=days)
                 campaign.status = 'ACTIVE'
                 campaign.save()
                 
                 return Response({'status': 'relaunched', 'campaign_id': campaign.id})
        
        return Response({'error': 'Cannot relaunch this campaign'}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def create_checkout_session(self, request, pk=None):
        import stripe
        from django.conf import settings
        stripe.api_key = settings.STRIPE_SECRET_KEY
        
        campaign = self.get_object()
        if not hasattr(campaign, 'budget'):
            return Response({'error': 'Campaign has no budget'}, status=status.HTTP_400_BAD_REQUEST)
            
        try:
            checkout_session = stripe.checkout.Session.create(
                payment_method_types=['card'],
                line_items=[{
                    'price_data': {
                        'currency': 'usd',
                        'product_data': {
                            'name': f"Ad Campaign: {campaign.name}",
                        },
                        'unit_amount': int(campaign.budget.total_budget * 100),
                    },
                    'quantity': 1,
                }],
                mode='payment',
                success_url=settings.FRONTEND_URL + '/ads?success=true&campaign_id=' + str(campaign.id) + '&session_id={CHECKOUT_SESSION_ID}',
                cancel_url=settings.FRONTEND_URL + '/ads?canceled=true&campaign_id=' + str(campaign.id),
                metadata={
                    'campaign_id': campaign.id,
                    'type': 'ad_campaign'
                }
            )
            return Response({'url': checkout_session.url})
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['get'])
    def verify_payment(self, request, pk=None):
        import stripe
        from django.conf import settings
        stripe.api_key = settings.STRIPE_SECRET_KEY
        session_id = request.query_params.get('session_id')
        
        if not session_id:
            return Response({'error': 'Missing session_id'}, status=status.HTTP_400_BAD_REQUEST)
            
        try:
            session = stripe.checkout.Session.retrieve(session_id)
            if session.payment_status == 'paid' or session.status == 'complete':
                campaign = self.get_object()
                # Double check campaign ID in metadata
                if str(campaign.id) == session.metadata.get('campaign_id'):
                    campaign.status = 'ACTIVE'
                    campaign.save()
                    return Response({'status': 'paid', 'campaign_status': campaign.status})
            
            return Response({'status': session.payment_status})
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'])
    def track_click(self, request, pk=None):
        campaign = self.get_object()
        from django.utils import timezone
        today = timezone.now().date()
        
        analytics, created = AdAnalytics.objects.get_or_create(
            campaign=campaign, 
            date=today
        )
        analytics.clicks += 1
        analytics.save()
        
        return Response({'status': 'tracked'})

class AdAnalyticsViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = AdAnalyticsSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return AdAnalytics.objects.filter(campaign__user=self.request.user)
