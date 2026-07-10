from rest_framework import serializers
from .models import AdCampaign, AdAudience, AdCreative, AdBudget, AdAnalytics, AdReview


def build_promoted_content(video, request=None):
    """
    Payload compacto y estable de un video promocionado (boost), para que el
    frontend lo renderice como un item de feed con badge 'Patrocinado'.

    Se mantiene desacoplado del VideoZerializer (pesado, con likes/follows) a
    propósito: aquí solo viaja lo necesario para reproducir el video y atribuir
    al autor. Si en el futuro se necesita más, se extiende este único lugar.
    """
    if video is None:
        return None

    def _abs(url):
        if url and request is not None and not str(url).startswith(('http://', 'https://')):
            return request.build_absolute_uri(url)
        return url

    video_url = video.video_url or (_abs(video.video.url) if getattr(video, 'video', None) else None)

    author = getattr(video, 'user_id', None)
    author_data = None
    if author is not None:
        pic = getattr(author, 'profile_picture', None)
        # ¿El viewer ya sigue a este autor? Misma fórmula que el feed
        # (Follower.follower_user_id = seguido, user_id = quien sigue).
        is_following = False
        viewer = getattr(request, 'user', None) if request is not None else None
        if viewer is not None and getattr(viewer, 'is_authenticated', False):
            from apps.videos.models import Follower
            is_following = Follower.objects.filter(
                follower_user_id=author, user_id=viewer
            ).exists()
        author_data = {
            'id': author.id,
            'username': getattr(author, 'username', None),
            'profile_picture': _abs(pic.url) if pic else None,
            'is_following': is_following,
        }

    return {
        'video_id': video.id,
        'video_uuid': video.uuid,
        'media_type': video.media_type,
        'video_url': _abs(video_url),
        'thumbnail_url': _abs(video.thumbnail_url),
        'description': video.description or '',
        'duration': video.duration,
        'author': author_data,
    }


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

    # ── Boost de video propio ──────────────────────────────────────
    # Entrada: el frontend manda el uuid del video a promocionar.
    # Salida: is_boost + el payload del video para renderizarlo en el feed.
    promoted_video_uuid = serializers.CharField(write_only=True, required=False, allow_blank=True)
    is_boost            = serializers.BooleanField(read_only=True)
    promoted_content    = serializers.SerializerMethodField()

    class Meta:
        model  = AdCampaign
        fields = [
            'id', 'user', 'name', 'objective', 'status', 'rejection_reason',
            'start_date', 'end_date', 'created_at', 'updated_at',
            'audience', 'creative', 'budget', 'analytics', 'review',
            'total_reach', 'total_impressions', 'total_clicks',
            'ctr', 'cpm', 'cpc', 'spent_pct',
            'promoted_video_uuid', 'is_boost', 'promoted_content',
        ]
        read_only_fields = ['user', 'created_at', 'updated_at']

    def get_promoted_content(self, obj):
        if not obj.promoted_video_id:
            return None
        return build_promoted_content(obj.promoted_video, request=self.context.get('request'))

    def validate_promoted_video_uuid(self, value):
        """Resuelve el uuid a un Video, exigiendo que sea del usuario y publicable."""
        if not value:
            return None
        from apps.videos.models import Video
        request = self.context.get('request')
        try:
            video = Video.objects.get(uuid=value)
        except Video.DoesNotExist:
            raise serializers.ValidationError("El video a promocionar no existe.")
        if request and video.user_id_id != request.user.id:
            raise serializers.ValidationError("Solo puedes promocionar tus propios videos.")
        if video.status != 'ready':
            raise serializers.ValidationError("El video aún no está listo para promocionarse.")
        if video.privacy != video.PRIVACY_PUBLIC:
            raise serializers.ValidationError("Solo se pueden promocionar videos públicos.")
        return video

    def validate(self, attrs):
        """
        Garantiza la coherencia del creative:
        - Boost (con promoted_video_uuid): NO necesita creative externo.
        - Anuncio externo (sin boost) recién creado: necesita creative con media.
        """
        is_create = self.instance is None
        is_boost  = bool(attrs.get('promoted_video_uuid'))
        creative  = attrs.get('creative')

        if is_create and not is_boost:
            if not creative or not creative.get('media_file'):
                raise serializers.ValidationError(
                    {'creative': "Un anuncio externo requiere un creative con archivo de medios."}
                )
        return attrs

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

        # Boost: el validator ya resolvió el uuid a un objeto Video (o None).
        promoted_video = validated_data.pop('promoted_video_uuid', None)
        if promoted_video is not None:
            validated_data['promoted_video'] = promoted_video
            # Un boost de contenido se cobra por impresión: forzamos CPM.
            if budget_data:
                budget_data['bidding_model'] = 'CPM'

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
