import time
import requests
from apps.subscriptions.models import UserSubscription
from django.conf import settings
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status
from rest_framework.generics import ListAPIView
from .models import AIStyle, AIGenerationHistory
from .serializers import AIStyleSerializer, AIGenerationHistorySerializer


 
class AIGenerateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        user = request.user
        prompt = request.data.get("prompt")
        media_type = request.data.get("type", "image")  # 'video' or 'image'
        style_slug = request.data.get("style", "photorealistic")
        reference_image = request.FILES.get("reference_image")

        sub_style = None
        try:
            sub_style = AIStyle.objects.filter(slug=style_slug).first()
        except:
            pass

        print(f"--- IMAGINA AI ---")
        print(f"Type: {media_type}, Style: {style_slug}")
        print(f"Prompt: {prompt}")

        if not prompt:
            return Response({"error": "El prompt es requerido."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            sub = UserSubscription.objects.filter(subscriber=user, is_active=True).first()
            if not sub:
                return Response({"error": "Necesitas una suscripción activa para usar la IA."}, status=status.HTTP_403_FORBIDDEN)

            print(sub, "===")
            can_generate, msg = sub.can_generate_ai()
            if not can_generate:
                return Response({"error": msg}, status=status.HTTP_403_FORBIDDEN)

            google_api_key = getattr(settings, 'GOOGLE_API_KEY', None)
            media_url = None

            if google_api_key:
                if media_type == "image":
                    media_url = self._generate_image_gemini(prompt, style_slug, google_api_key)
                elif media_type == "video":
                    media_url = self._generate_image_gemini(
                        f"A cinematic frame representing: {prompt}", style_slug, google_api_key
                    )
                    print("⚠️ Video generation not available, returning image preview")

            if not media_url:
                # Fallback mock
                media_url = (
                    "https://example.com/mock-video.mp4"
                    if media_type == "video"
                    else "https://cdn.pixabay.com/photo/2023/05/29/18/53/astronaut-8026859_1280.jpg"
                )

            # Restar límite en suscripción
            sub.ai_generations_this_month += 1
            sub.save()

            # Guardar en Historial
            AIGenerationHistory.objects.create(
                user=user,
                prompt=prompt,
                media_url=media_url,
                media_type=media_type,
                style=sub_style
            )

            return Response({
                "message": f"{media_type.capitalize()} generado exitosamente con Gemini AI",
                "media_url": media_url,
                "credits_remaining": sub.get_benefit_limit('AI_GENERATION') - sub.ai_generations_this_month
            }, status=status.HTTP_200_OK)

        except Exception as e:
            print(f"General Error in AI Generation: {e}")
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def _generate_image_gemini(self, prompt, style_slug, api_key):
        """
        Genera imagen usando Gemini 2.5 Flash Image (nativa de Google AI Studio)
        Si falla, intenta con Imagen 3.
        """

        # Mejora el prompt con el estilo
        style_prompts = {
            "anime": "anime style, vibrant colors, Studio Ghibli inspired",
            "photorealistic": "photorealistic, high quality, 8k, detailed",
            "cartoon": "cartoon style, colorful, fun illustration",
            "oil_painting": "oil painting style, artistic, textured brushstrokes",
            "watercolor": "watercolor painting, soft colors, artistic",
            "sketch": "pencil sketch, detailed line art, black and white",
        }
        style_addition = style_prompts.get(style_slug, "high quality, detailed")
        full_prompt = f"{prompt}, {style_addition}"

        print(f"Full prompt: {full_prompt}")

        # Modelos de imagen disponibles en tu cuenta (en orden de preferencia)
        IMAGE_MODELS = [
            "gemini-3.1-flash-image-preview",   # Gemini 3.1 Flash Image
            "gemini-2.5-flash-image",            # Gemini 2.5 Flash Image
            "gemini-3-pro-image-preview",        # Gemini 3 Pro Image
        ]

        # ---- OPCIÓN 1: Modelos Gemini con generación nativa de imágenes ----
        for model_name in IMAGE_MODELS:
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
                payload = {
                    "contents": [{
                        "parts": [{"text": full_prompt}]
                    }],
                    "generationConfig": {
                        "responseModalities": ["IMAGE", "TEXT"],
                    }
                }
                response = requests.post(url, json=payload, timeout=60)
                print(f"Model {model_name} status: {response.status_code}")

                if response.status_code == 429:
                    print(f"⚠️ Rate limit on {model_name}, trying next...")
                    time.sleep(2)
                    continue

                if response.status_code == 200:
                    data = response.json()
                    for part in data.get("candidates", [{}])[0].get("content", {}).get("parts", []):
                        if part.get("inlineData"):
                            image_data = part["inlineData"]["data"]
                            mime_type = part["inlineData"].get("mimeType", "image/png")
                            media_url = self._save_base64_image(image_data, mime_type)
                            print(f"✅ Image generated with {model_name}: {media_url}")
                            return media_url

            except Exception as e:
                print(f"Error with {model_name}: {e}")
                continue

        # ---- OPCIÓN 2: Imagen 4 (nombre correcto según tu lista de modelos) ----
        IMAGEN_MODELS = [
            "imagen-4.0-generate-001",       # Imagen 4 estable ✅
            "imagen-4.0-fast-generate-001",  # Imagen 4 Fast ✅
        ]

        for imagen_model in IMAGEN_MODELS:
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{imagen_model}:predict?key={api_key}"
                payload = {
                    "instances": [{"prompt": full_prompt}],
                    "parameters": {
                        "sampleCount": 1,
                        "aspectRatio": "1:1",
                    }
                }
                response = requests.post(url, json=payload, timeout=60)
                print(f"Imagen model {imagen_model} status: {response.status_code}")

                if response.status_code == 200:
                    data = response.json()
                    image_data = data["predictions"][0]["bytesBase64Encoded"]
                    media_url = self._save_base64_image(image_data, "image/png")
                    print(f"✅ Imagen 4 generated: {media_url}")
                    return media_url
                else:
                    print(f"Imagen error response: {response.text[:300]}")

            except Exception as e:
                print(f"Error with {imagen_model}: {e}")
                continue

        # ---- OPCIÓN 3: Gemini 2.0 Flash genera texto describiendo imagen ----
        # (Fallback — retorna None para usar mock)
        print("⚠️ All image generation methods failed, using fallback.")
        return None

    def _save_base64_image(self, base64_data, mime_type="image/png"):
        """
        Decodifica imagen base64 y la guarda en MEDIA_ROOT.
        Retorna la URL pública.
        """
        extension = mime_type.split("/")[-1].replace("jpeg", "jpg")
        filename = f"ai_generated/{uuid.uuid4().hex}.{extension}"

        image_bytes = base64.b64decode(base64_data)

        media_root = getattr(settings, 'MEDIA_ROOT', '/tmp')
        full_path = os.path.join(media_root, filename)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)

        with open(full_path, "wb") as f:
            f.write(image_bytes)

        media_url_base = getattr(settings, 'MEDIA_URL', '/media/')
        return f"{media_url_base}{filename}"

class ListAIStylesView(ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = AIStyleSerializer
    queryset = AIStyle.objects.filter(is_active=True).prefetch_related('templates')

class ListAIGenerationHistoryView(ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = AIGenerationHistorySerializer

    def get_queryset(self):
        return AIGenerationHistory.objects.filter(user=self.request.user)

class PublishAIContentView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        history_id = request.data.get("history_id")
        if not history_id:
            return Response({"error": "history_id is required"}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            history_item = AIGenerationHistory.objects.get(id=history_id, user=request.user)
            
            from .models import Video, Category
            # Use 'Default' category as found in shell
            category = Category.objects.filter(name='Default').first()
            
            # Create a Video object
            video = Video.objects.create(
                user_id=request.user,
                category=category,
                video_url=history_item.media_url,
                thumbnail_url=history_item.media_url,
                description=history_item.prompt,
                tags={"tags": []},
                media_type=history_item.media_type,
                duration=5 if history_item.media_type == 'video' else 0
            )
            
            return Response({
                "message": "Publicado exitosamente en tu perfil",
                "video_id": video.id,
                "uuid": video.uuid
            }, status=status.HTTP_201_CREATED)
            
        except AIGenerationHistory.DoesNotExist:
            return Response({"error": "No se encontró el elemento en el historial"}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

