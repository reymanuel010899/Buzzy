from django.utils import translation


class UserLanguageMiddleware:
    """
    Activate the authenticated user's stored language preference for every request.
    Falls back to the Accept-Language header (handled by Django's LocaleMiddleware logic).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        language = None

        # Use stored preference for authenticated users
        if hasattr(request, "user") and request.user.is_authenticated:
            language = getattr(request.user, "language", None)

        # Fall back to Accept-Language header
        if not language:
            language = translation.get_language_from_request(request)

        if language:
            translation.activate(language)
            request.LANGUAGE_CODE = translation.get_language()

        response = self.get_response(request)
        return response
