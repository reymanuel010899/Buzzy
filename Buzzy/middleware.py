# myapp/middleware.py
from django.http import JsonResponse
from django.urls import resolve
import jwt
from django.conf import settings

class TokenAuthenticationMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = resolve(request.path_info).url_name
        public_routes = ['login', 'register', 'forgot_password']
        response = self.get_response(request)
        if request.method == 'OPTIONS': 
            return response
        print(request.headers.get('Authorization'))
        # if path not in public_routes:
        #     auth_header = request.headers.get('Authorization')

        #     if not auth_header:
        #         return JsonResponse({'detail': 'Authorization token is missing'}, status=401)

        #     if not auth_header.startswith('Bearer '):
        #         return JsonResponse({'detail': 'Invalid token format'}, status=401)

        #     token = auth_header.split(' ')[1]

        #     try:
        #         payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        #         request.user = payload 
        #     except jwt.ExpiredSignatureError:
        #         return JsonResponse({'detail': 'Token has expired'}, status=401)
        #     except jwt.InvalidTokenError:
        #         return JsonResponse({'detail': 'Invalid token'}, status=401)


        # response = self.get_response(request)

        return response
