from rest_framework import serializers
from django.conf import settings as django_settings
from .models import BuzzyBanner


def _abs(request, path):
    if not path:
        return None
    url = str(path)
    if url.startswith('http'):
        return url
    if request:
        return request.build_absolute_uri(f'/media/{url}')
    base = getattr(django_settings, 'BACKEND_URL', 'http://localhost:8000').rstrip('/')
    return f"{base}/media/{url}"


class BuzzyBannerSerializer(serializers.ModelSerializer):
    expires_at = serializers.DateTimeField(format="%Y-%m-%dT%H:%M:%SZ", allow_null=True)
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = BuzzyBanner
        fields = (
            'id', 'title', 'message', 'type', 'effect',
            'background_color', 'text_color', 'accent_color',
            'reveal_content', 'countdown_label',
            'image_url', 'action_url', 'action_label',
            'priority', 'expires_at', 'created_at',
        )

    def get_image_url(self, obj):
        if not obj.image:
            return None
        request = self.context.get('request')
        return _abs(request, obj.image)
