import random
import math
import json
import csv
import io
from decimal import Decimal
from datetime import timedelta

from django.db.models import Sum, Count, Q, F
from django.utils import timezone
from django.http import HttpResponse
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle


class TrackRateThrottle(UserRateThrottle):
    rate = '10/min'

from .models import (
    AdCampaign, AdAnalytics, AdImpression, AdDailyFrequency,
    AdReview, AdBudget, AdAudience, AdsConfig,
)
from .serializers import AdCampaignSerializer, AdAnalyticsSerializer


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def haversine_distance(lat1, lon1, lat2, lon2):
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _cost_per_impression(campaign):
    """Returns the cost in USD for one impression based on bidding model."""
    cfg = AdsConfig.get()
    budget = getattr(campaign, 'budget', None)
    if not budget:
        return cfg.cpm_rate / Decimal('1000')
    if budget.bidding_model == 'CPM':
        return cfg.cpm_rate / Decimal('1000')
    # CPC — no cost at impression time; cost happens on click
    return Decimal('0')


def _cost_per_click(campaign):
    cfg = AdsConfig.get()
    budget = getattr(campaign, 'budget', None)
    if not budget:
        return Decimal('0')
    if budget.bidding_model == 'CPC':
        return cfg.cpc_rate
    return Decimal('0')


# ─────────────────────────────────────────────
# ViewSets
# ─────────────────────────────────────────────

class AdCampaignViewSet(viewsets.ModelViewSet):
    serializer_class = AdCampaignSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        public_actions = ['track_impression', 'track_click', 'serve', 'config']
        if self.action in public_actions:
            return AdCampaign.objects.select_related('audience', 'creative', 'budget').all()
        return AdCampaign.objects.select_related(
            'audience', 'creative', 'budget', 'review'
        ).filter(user=self.request.user)

    # ── Create ────────────────────────────────
    def create(self, request, *args, **kwargs):
        """Accept flattened FormData with dot-notation keys."""
        nested_data = {}
        for key, value in request.data.items():
            if '.' in key:
                parent, child = key.split('.', 1)
                nested_data.setdefault(parent, {})
                if child in ('locations', 'interests'):
                    try:
                        nested_data[parent][child] = json.loads(value)
                    except Exception:
                        nested_data[parent][child] = value
                else:
                    nested_data[parent][child] = value
            else:
                nested_data[key] = value

        serializer = self.get_serializer(data=nested_data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    # ── Delivery config (public) ──────────────
    @action(detail=False, methods=['get'])
    def config(self, request):
        cfg = AdsConfig.get()
        return Response({
            'ad_every_nth_video':  cfg.ad_every_nth_video,
            'ad_cooldown_seconds': cfg.ad_cooldown_seconds,
            'ads_refresh_seconds': cfg.ads_refresh_seconds,
        })

    # ── Serve ads to feed ─────────────────────
    @action(detail=False, methods=['get'])
    def serve(self, request):
        today = timezone.now().date()
        user = request.user

        # Read user GPS sent by frontend
        try:
            user_lat = float(request.query_params['lat'])
            user_lng = float(request.query_params['lng'])
        except (KeyError, ValueError, TypeError):
            user_lat = None
            user_lng = None

        active = []
        import logging
        logger = logging.getLogger('ads.serve')
        # select_related promoted_video + su autor para no hacer N+1 al serializar boosts.
        all_campaigns = (
            AdCampaign.objects
            .select_related('audience', 'budget', 'promoted_video', 'promoted_video__user_id')
            .all()
        )
        logger.warning(f"[ADS SERVE] user={user} total_campaigns={all_campaigns.count()} user_lat={user_lat} user_lng={user_lng}")

        for campaign in all_campaigns:
            if not campaign.is_active:
                logger.warning(f"[ADS SERVE] SKIP campaign={campaign.id} '{campaign.name}' reason=not_active status={campaign.status}")
                continue

            # No mostrarle a un autor su propio boost (además, sus impresiones no se cobran).
            if campaign.user_id == user.id:
                logger.warning(f"[ADS SERVE] SKIP campaign={campaign.id} reason=own_campaign")
                continue

            # Boost cuyo video fue borrado (promoted_video quedó NULL): no se puede servir.
            if campaign.promoted_video_id is None and not hasattr(campaign, 'creative'):
                logger.warning(f"[ADS SERVE] SKIP campaign={campaign.id} reason=no_content")
                continue

            aud = getattr(campaign, 'audience', None)
            bud = getattr(campaign, 'budget', None)
            if not aud or not bud:
                logger.warning(f"[ADS SERVE] SKIP campaign={campaign.id} reason=no_audience_or_budget")
                continue

            # 1. Location targeting
            # - If viewer shared GPS → use precise geo-radius check.
            # - If viewer did NOT share GPS → skip geo-radius (can't confirm exclusion); show ad.
            # - Country/text fallback: only if GPS confirmed mismatch is not available.
            # - Locations list containing only "Mi Ubicación Actual" → no restriction, show to all.
            #
            # Boost de video propio: SIN segmentación geográfica — se muestra a todos
            # los usuarios de cualquier lugar, así que omitimos el filtro de ubicación.
            has_geo_target     = (not campaign.is_boost) and bool(aud.latitude and aud.longitude)
            real_locs = [] if campaign.is_boost else [loc for loc in (aud.locations or []) if loc and loc.strip() != "Mi Ubicación Actual"]
            has_country_target = bool(real_locs)

            if has_geo_target or has_country_target:
                location_ok = False

                if has_geo_target:
                    if user_lat is not None and user_lng is not None:
                        # Viewer shared GPS — check radius
                        try:
                            dist = haversine_distance(user_lat, user_lng,
                                                      float(aud.latitude), float(aud.longitude))
                            if dist <= float(aud.radius or 50):
                                location_ok = True
                        except (ValueError, TypeError):
                            location_ok = True  # parse error → don't exclude
                    else:
                        # Viewer has no GPS → can't verify distance; show the ad
                        location_ok = True

                if not location_ok and has_country_target:
                    user_country = getattr(user, 'country', None)
                    if not user_country:
                        location_ok = True  # unknown country → show
                    else:
                        country_name = getattr(user_country, 'name', str(user_country)).lower()
                        if any(country_name in loc.lower() or loc.lower() in country_name
                               for loc in real_locs):
                            location_ok = True

                if not location_ok and not has_geo_target and not has_country_target:
                    # Only placeholder entries → show to everyone
                    location_ok = True

                if not location_ok:
                    logger.warning(f"[ADS SERVE] SKIP campaign={campaign.id} reason=location user_country={getattr(user,'country',None)} real_locs={real_locs} has_geo={has_geo_target} user_gps={user_lat},{user_lng}")
                    continue

            # 3. Daily budget cap
            daily_target = bud.daily_budget * 700
            analytics = AdAnalytics.objects.filter(campaign=campaign, date=today).first()
            if analytics and analytics.impressions >= daily_target:
                logger.warning(f"[ADS SERVE] SKIP campaign={campaign.id} reason=daily_budget_cap impressions={analytics.impressions} target={daily_target}")
                continue

            # 4. Frequency cap per user per day
            if aud.max_frequency > 0:
                freq = AdDailyFrequency.objects.filter(
                    campaign=campaign, user=user, date=today
                ).first()
                if freq and freq.view_count >= aud.max_frequency:
                    logger.warning(f"[ADS SERVE] SKIP campaign={campaign.id} reason=frequency_cap views={freq.view_count} max={aud.max_frequency}")
                    continue

            logger.warning(f"[ADS SERVE] PASS campaign={campaign.id} '{campaign.name}'")
            active.append(campaign)

        random.shuffle(active)
        result = active[:5]
        logger.warning(f"[ADS SERVE] returning {len(result)} ads to user={user}")
        return Response(self.get_serializer(result, many=True).data)

    # ── Track impression ──────────────────────
    @action(detail=True, methods=['post'], throttle_classes=[TrackRateThrottle])
    def track_impression(self, request, pk=None):
        from django.db import transaction
        campaign = self.get_object()
        user = request.user

        # Campaign owner cannot generate their own impressions
        if campaign.user_id == user.id:
            return Response({'status': 'skipped'})

        today = timezone.now().date()

        # El frontend solo llama a este endpoint cuando el usuario vio el anuncio
        # el tiempo mínimo (>= MIN_VIEW_SECONDS), aunque haya scrolleado/cerrado la
        # app antes de poder saltarlo. Por tanto, toda impresión que llega aquí es
        # facturable: cuenta para frecuencia, analytics y cobra al anunciante.

        # Frequency tracking — anti-spam por usuario/día.
        freq, _ = AdDailyFrequency.objects.get_or_create(campaign=campaign, user=user, date=today)
        AdDailyFrequency.objects.filter(pk=freq.pk).update(view_count=F('view_count') + 1)

        # Lifetime dedup: marca que este usuario ya recibió esta campaña alguna vez.
        AdImpression.objects.get_or_create(campaign=campaign, user=user)

        # Record analytics
        analytics, _ = AdAnalytics.objects.get_or_create(campaign=campaign, date=today)
        AdAnalytics.objects.filter(pk=analytics.pk).update(impressions=F('impressions') + 1)

        # Deduct budget — atomic to prevent race condition
        bud = getattr(campaign, 'budget', None)
        if bud:
            cost = _cost_per_impression(campaign)
            with transaction.atomic():
                updated = AdBudget.objects.select_for_update().filter(
                    pk=bud.pk, spent_amount__lt=F('total_budget')
                ).update(spent_amount=F('spent_amount') + cost)
                if updated:
                    bud.refresh_from_db()
                    if bud.spent_amount >= bud.total_budget:
                        AdCampaign.objects.filter(pk=campaign.pk).update(status='COMPLETED')

        return Response({'status': 'tracked'})

    # ── Track click ───────────────────────────
    @action(detail=True, methods=['post'], throttle_classes=[TrackRateThrottle])
    def track_click(self, request, pk=None):
        from django.db import transaction
        campaign = self.get_object()

        # Campaign owner cannot click their own ad
        if campaign.user_id == request.user.id:
            return Response({'status': 'skipped'})

        today = timezone.now().date()

        analytics, _ = AdAnalytics.objects.get_or_create(campaign=campaign, date=today)
        AdAnalytics.objects.filter(pk=analytics.pk).update(clicks=F('clicks') + 1)

        # CPC: charge on click — atomic to prevent race condition
        bud = getattr(campaign, 'budget', None)
        if bud and bud.bidding_model == 'CPC':
            cost = _cost_per_click(campaign)
            with transaction.atomic():
                updated = AdBudget.objects.select_for_update().filter(
                    pk=bud.pk, spent_amount__lt=F('total_budget')
                ).update(spent_amount=F('spent_amount') + cost)
                if updated:
                    bud.refresh_from_db()
                    if bud.spent_amount >= bud.total_budget:
                        AdCampaign.objects.filter(pk=campaign.pk).update(status='COMPLETED')

        return Response({'status': 'tracked'})

    # ── Dashboard stats ───────────────────────
    @action(detail=False, methods=['get'])
    def dashboard_stats(self, request):
        user_campaigns = AdCampaign.objects.filter(user=request.user)
        active_ids = list(user_campaigns.filter(status='ACTIVE').values_list('id', flat=True))
        draft_ids  = list(user_campaigns.filter(status='DRAFT').values_list('id', flat=True))
        all_ids    = list(user_campaigns.values_list('id', flat=True))

        # Reach: unique users
        total_reach = AdImpression.objects.filter(
            campaign_id__in=active_ids
        ).values('user').distinct().count()

        # Impressions & clicks
        agg = AdAnalytics.objects.filter(campaign_id__in=active_ids).aggregate(
            total_impressions=Sum('impressions'),
            total_clicks=Sum('clicks'),
        )
        total_impressions = agg['total_impressions'] or 0
        total_clicks      = agg['total_clicks'] or 0

        # CTR
        ctr = round((total_clicks / total_impressions) * 100, 2) if total_impressions else 0.0

        # Spent
        total_spent = AdBudget.objects.filter(
            campaign_id__in=active_ids
        ).aggregate(s=Sum('spent_amount'))['s'] or Decimal('0')

        # CPM = (spent / impressions) * 1000
        cpm = round(float(total_spent) / total_impressions * 1000, 4) if total_impressions else 0.0

        # CPC = spent / clicks
        cpc = round(float(total_spent) / total_clicks, 4) if total_clicks else 0.0

        # Real reach estimation for audience (live user count)
        real_reach = self._estimate_real_reach(request.user)

        # Timeline: last 14 days across all campaigns
        timeline = self._build_timeline(all_ids, days=14)

        return Response({
            'total_reach':       total_reach,
            'total_impressions': total_impressions,
            'total_interactions': total_clicks,
            'total_spent':       float(total_spent),
            'active_campaigns':  len(active_ids),
            'draft_campaigns':   len(draft_ids),
            'ctr':               ctr,
            'cpm':               cpm,
            'cpc':               cpc,
            'real_reach_pool':   real_reach,
            'timeline':          timeline,
        })

    def _estimate_real_reach(self, requesting_user):
        """Count real active users in the platform as potential reach."""
        from django.contrib.auth import get_user_model
        User = get_user_model()
        return User.objects.filter(is_active=True).exclude(id=requesting_user.id).count()

    def _build_timeline(self, campaign_ids, days=14):
        """Returns daily impressions + clicks for the last N days."""
        today = timezone.now().date()
        result = []
        for i in range(days - 1, -1, -1):
            d = today - timedelta(days=i)
            agg = AdAnalytics.objects.filter(
                campaign_id__in=campaign_ids, date=d
            ).aggregate(imp=Sum('impressions'), clk=Sum('clicks'))
            result.append({
                'date':        d.strftime('%Y-%m-%d'),
                'impressions': agg['imp'] or 0,
                'clicks':      agg['clk'] or 0,
            })
        return result

    # ── Per-campaign detail stats ─────────────
    @action(detail=True, methods=['get'])
    def stats(self, request, pk=None):
        """Detailed stats for a single campaign."""
        campaign = self.get_object()
        analytics_qs = AdAnalytics.objects.filter(campaign=campaign).order_by('date')

        total_imp = sum(a.impressions for a in analytics_qs)
        total_clk = sum(a.clicks for a in analytics_qs)
        bud = getattr(campaign, 'budget', None)
        spent = float(bud.spent_amount) if bud else 0

        ctr = round((total_clk / total_imp) * 100, 2) if total_imp else 0.0
        cpm = round(spent / total_imp * 1000, 4) if total_imp else 0.0
        cpc = round(spent / total_clk, 4) if total_clk else 0.0

        timeline = [
            {
                'date':        a.date.strftime('%Y-%m-%d'),
                'impressions': a.impressions,
                'clicks':      a.clicks,
                'ctr':         a.ctr,
            }
            for a in analytics_qs
        ]

        reach = AdImpression.objects.filter(campaign=campaign).values('user').distinct().count()

        return Response({
            'campaign_id':       campaign.id,
            'campaign_name':     campaign.name,
            'total_impressions': total_imp,
            'total_clicks':      total_clk,
            'total_reach':       reach,
            'total_spent':       spent,
            'ctr':               ctr,
            'cpm':               cpm,
            'cpc':               cpc,
            'timeline':          timeline,
            'budget':            {
                'daily_budget': float(bud.daily_budget) if bud else 0,
                'total_budget': float(bud.total_budget) if bud else 0,
                'spent_amount': spent,
                'remaining':    float(bud.total_budget - bud.spent_amount) if bud else 0,
                'bidding_model': bud.bidding_model if bud else 'CPM',
            },
        })

    # ── Real reach estimation API ─────────────
    @action(detail=False, methods=['get', 'post'])
    def estimate_reach(self, request):
        """
        Returns total reach (low/high) plus a per-location breakdown.
        If no locations supplied, uses the full active user base as default.
        """
        import json as _json
        from django.contrib.auth import get_user_model
        from datetime import date
        User = get_user_model()

        src      = request.query_params if request.method == 'GET' else request.data
        age_min  = int(src.get('age_min', 18))
        age_max  = int(src.get('age_max', 65))
        budget   = float(src.get('total_budget', 50))

        # locations can come as JSON string or plain string list
        raw_locs = src.get('locations', '[]')
        try:
            locations = _json.loads(raw_locs) if isinstance(raw_locs, str) else list(raw_locs)
        except Exception:
            locations = []
        # Remove placeholder
        locations = [l for l in locations if l and l != "Mi Ubicación Actual"]

        # Base queryset — active users excluding self
        qs = User.objects.filter(is_active=True).exclude(id=request.user.id)

        # Age filter
        today = date.today()
        if hasattr(User, 'birthdate'):
            from django.db.models import Q
            min_birth = date(today.year - age_max, today.month, today.day)
            max_birth = date(today.year - age_min, today.month, today.day)
            qs = qs.filter(
                Q(birthdate__isnull=True) |
                Q(birthdate__gte=min_birth, birthdate__lte=max_birth)
            )

        base_pool = qs.count()

        # CPM-based max impressions budget can buy
        cfg             = AdsConfig.get()
        cpm_rate        = float(cfg.cpm_rate)
        ctr             = float(cfg.ctr_estimate)
        max_impressions = int((budget / cpm_rate) * 1000)
        reach_high      = min(base_pool, max_impressions)
        reach_low       = min(base_pool, int(max_impressions * (1 - ctr * 5)))

        # ── Per-location breakdown ─────────────────────────────────────────
        breakdown = []

        if not locations:
            # No locations → show single "Global" entry with full reach
            breakdown.append({
                'location':   'Global (por defecto)',
                'reach_low':  reach_low,
                'reach_high': reach_high,
                'pct':        100,
            })
        else:
            # Count real users per country name match
            loc_pools = {}
            for loc in locations:
                loc_lower = loc.lower()
                # Match users whose country name contains the location string
                count = qs.filter(country__name__icontains=loc_lower).count()
                loc_pools[loc] = count

            total_loc_pool = sum(loc_pools.values()) or 1  # avoid /0

            for loc, pool in loc_pools.items():
                pct = pool / total_loc_pool  # proportion of this location
                loc_low  = min(pool, int(reach_low  * pct))
                loc_high = min(pool, int(reach_high * pct))
                breakdown.append({
                    'location':   loc,
                    'reach_low':  loc_low,
                    'reach_high': loc_high,
                    'pct':        round(pct * 100, 1),
                })

        return Response({
            'pool_size':       base_pool,
            'reach_low':       reach_low,
            'reach_high':      reach_high,
            'max_impressions': max_impressions,
            'breakdown':       breakdown,
        })

    # ── Export CSV ────────────────────────────
    @action(detail=False, methods=['get'])
    def export_csv(self, request):
        """Download all campaign analytics as CSV."""
        campaigns = AdCampaign.objects.filter(user=request.user).select_related('budget')

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            'Campaign', 'Objective', 'Status', 'Start', 'End',
            'Total Budget', 'Spent', 'Daily Budget',
            'Impressions', 'Clicks', 'CTR (%)', 'CPM ($)', 'CPC ($)', 'Reach',
        ])

        for campaign in campaigns:
            analytics_qs = AdAnalytics.objects.filter(campaign=campaign)
            total_imp = sum(a.impressions for a in analytics_qs)
            total_clk = sum(a.clicks for a in analytics_qs)
            bud = getattr(campaign, 'budget', None)
            spent = float(bud.spent_amount) if bud else 0
            ctr = round((total_clk / total_imp) * 100, 2) if total_imp else 0.0
            cpm = round(spent / total_imp * 1000, 4) if total_imp else 0.0
            cpc = round(spent / total_clk, 4) if total_clk else 0.0
            reach = AdImpression.objects.filter(campaign=campaign).values('user').distinct().count()

            writer.writerow([
                campaign.name,
                campaign.objective,
                campaign.status,
                campaign.start_date.strftime('%Y-%m-%d') if campaign.start_date else '',
                campaign.end_date.strftime('%Y-%m-%d') if campaign.end_date else '',
                float(bud.total_budget) if bud else 0,
                spent,
                float(bud.daily_budget) if bud else 0,
                total_imp,
                total_clk,
                ctr,
                cpm,
                cpc,
                reach,
            ])

        response = HttpResponse(output.getvalue(), content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="buzzy_ads_report.csv"'
        return response

    # ── Submit for review ─────────────────────
    @action(detail=True, methods=['post'])
    def submit_review(self, request, pk=None):
        """Advertiser submits campaign for moderation after payment."""
        campaign = self.get_object()
        if campaign.status not in ('DRAFT',):
            return Response({'error': 'Only DRAFT campaigns can be submitted for review.'}, status=400)

        campaign.status = 'IN_REVIEW'
        campaign.save()

        AdReview.objects.get_or_create(campaign=campaign)
        return Response({'status': 'in_review'})

    # ── Moderator: approve ────────────────────
    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        """Staff only: approve a campaign."""
        if not request.user.is_staff:
            return Response({'error': 'Not authorized.'}, status=403)
        campaign = self.get_object()
        campaign.status = 'ACTIVE'
        campaign.save()
        review = getattr(campaign, 'review', None)
        if review:
            review.decision = 'APPROVED'
            review.reviewed_at = timezone.now()
            review.reviewed_by = request.user
            review.save()
        return Response({'status': 'approved'})

    # ── Moderator: reject ─────────────────────
    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        """Staff only: reject a campaign with a reason."""
        if not request.user.is_staff:
            return Response({'error': 'Not authorized.'}, status=403)
        campaign = self.get_object()
        reason = request.data.get('reason', '')
        campaign.status = 'REJECTED'
        campaign.rejection_reason = reason
        campaign.save()
        review = getattr(campaign, 'review', None)
        if review:
            review.decision = 'REJECTED'
            review.rejection_reason = reason
            review.reviewed_at = timezone.now()
            review.reviewed_by = request.user
            review.save()
        return Response({'status': 'rejected', 'reason': reason})

    # ── Relaunch ──────────────────────────────
    @action(detail=True, methods=['post'])
    def relaunch(self, request, pk=None):
        campaign = self.get_object()
        if campaign.status not in ('COMPLETED', 'PAUSED', 'REJECTED'):
            return Response({'error': 'Cannot relaunch this campaign.'}, status=400)

        bud = getattr(campaign, 'budget', None)
        if bud:
            bud.spent_amount = Decimal('0.00')
            bud.save()
            days = max(1, int(bud.total_budget / bud.daily_budget))
            campaign.start_date = timezone.now()
            campaign.end_date = campaign.start_date + timedelta(days=days)

        campaign.status = 'IN_REVIEW'   # must go through moderation again
        campaign.rejection_reason = ''
        campaign.save()

        AdReview.objects.update_or_create(
            campaign=campaign,
            defaults={'decision': 'PENDING', 'reviewed_at': None, 'reviewed_by': None, 'rejection_reason': ''}
        )

        # Fire auto-review task
        from .tasks import auto_review_campaign
        auto_review_campaign.delay(campaign.id)

        return Response({'status': 'in_review', 'campaign_id': campaign.id})

    # ── Stripe checkout ───────────────────────
    @action(detail=True, methods=['post'])
    def create_checkout_session(self, request, pk=None):
        import stripe
        from django.conf import settings as dj_settings
        stripe.api_key = dj_settings.STRIPE_SECRET_KEY

        campaign = self.get_object()
        bud = getattr(campaign, 'budget', None)
        if not bud:
            return Response({'error': 'Campaign has no budget.'}, status=400)

        frontend_url = dj_settings.FRONTEND_URL.rstrip('/')

        try:
            session = stripe.checkout.Session.create(
                payment_method_types=['card'],
                line_items=[{
                    'price_data': {
                        'currency': 'usd',
                        'product_data': {'name': f"Buzzy Ad Campaign: {campaign.name}"},
                        'unit_amount': int(bud.total_budget * 100),
                    },
                    'quantity': 1,
                }],
                mode='payment',
                success_url=(
                    frontend_url
                    + f'/ads/campaign-success?campaign_id={campaign.id}&session_id={{CHECKOUT_SESSION_ID}}'
                ),
                cancel_url=(
                    frontend_url + f'/ads?canceled=true&campaign_id={campaign.id}'
                ),
                metadata={'campaign_id': campaign.id, 'type': 'ad_campaign'},
            )
            return Response({'url': session.url})
        except Exception as e:
            return Response({'error': str(e)}, status=500)

    # ── Stripe verify ─────────────────────────
    @action(detail=True, methods=['get'])
    def verify_payment(self, request, pk=None):
        import stripe
        from django.conf import settings as dj_settings
        stripe.api_key = dj_settings.STRIPE_SECRET_KEY

        session_id = request.query_params.get('session_id')
        if not session_id:
            return Response({'error': 'Missing session_id.'}, status=400)

        try:
            session = stripe.checkout.Session.retrieve(session_id)
            if session.payment_status == 'paid' or session.status == 'complete':
                campaign = self.get_object()
                if str(campaign.id) == session.metadata.get('campaign_id'):
                    # Set IN_REVIEW and launch automatic review task
                    campaign.status = 'IN_REVIEW'
                    campaign.save()
                    AdReview.objects.get_or_create(campaign=campaign)

                    # Fire auto-review task (runs in background via Celery)
                    from .tasks import auto_review_campaign
                    auto_review_campaign.delay(campaign.id)

                    return Response({'status': 'paid', 'campaign_status': 'IN_REVIEW'})
            return Response({'status': session.payment_status})
        except Exception as e:
            return Response({'error': str(e)}, status=500)

    # ── Pause / resume ────────────────────────
    @action(detail=True, methods=['post'])
    def pause(self, request, pk=None):
        campaign = self.get_object()
        if campaign.status != 'ACTIVE':
            return Response({'error': 'Only ACTIVE campaigns can be paused.'}, status=400)
        campaign.status = 'PAUSED'
        campaign.save()
        return Response({'status': 'paused'})

    @action(detail=True, methods=['post'])
    def resume(self, request, pk=None):
        campaign = self.get_object()
        if campaign.status != 'PAUSED':
            return Response({'error': 'Only PAUSED campaigns can be resumed.'}, status=400)
        campaign.status = 'ACTIVE'
        campaign.save()
        return Response({'status': 'active'})


class AdAnalyticsViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = AdAnalyticsSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return AdAnalytics.objects.filter(campaign__user=self.request.user)
