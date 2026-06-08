from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from django.db.models import Q, F
from django.db import IntegrityError
from apps.users.models import User, Trending, RecentSearch
from apps.videos.models import Video
from apps.users.serializers import DetailedUserSerializer, TrendingSerializer, RecentSearchSerializer
from apps.videos.serializers import VideoZerializer

class GlobalSearchView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        query = request.query_params.get('q', '').strip()
        if not query:
            return Response({"error": "Query parameter 'q' is required"}, status=status.HTTP_400_BAD_REQUEST)

        # 1. Save Recent Search
        RecentSearch.objects.update_or_create(
            user=request.user,
            term=query
        )

        # 2. Update Trending
        try:
            trending, created = Trending.objects.get_or_create(term=query)
            if not created:
                trending.count += 1
                trending.save()
        except IntegrityError:
            Trending.objects.filter(term=query).update(count=F('count') + 1)

        # 3. Search Users
        users = User.objects.filter(
            Q(username__icontains=query) | Q(first_name__icontains=query) | Q(email__icontains=query)
        )[:10]

        # 4. Search Videos (assuming tags or description)
        videos = Video.objects.filter(
            Q(description__icontains=query) | Q(tags__icontains=query)
        )[:10]

        return Response({
            "users": DetailedUserSerializer(users, many=True, context={'request': request}).data,
            "videos": VideoZerializer(videos, many=True, context={'request': request}).data,
        }, status=status.HTTP_200_OK)

class TrendingListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        trending = Trending.objects.all()[:10]
        return Response(TrendingSerializer(trending, many=True).data, status=status.HTTP_200_OK)

class RecentSearchView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        recent = RecentSearch.objects.filter(user=request.user)[:10]
        return Response(RecentSearchSerializer(recent, many=True).data, status=status.HTTP_200_OK)

    def delete(self, request):
        term = request.data.get('term')
        if term:
            RecentSearch.objects.filter(user=request.user, term=term).delete()
        else:
            RecentSearch.objects.filter(user=request.user).delete()
        return Response({"message": "Recent search cleared"}, status=status.HTTP_200_OK)
