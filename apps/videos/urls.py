from django.urls import path
from . import views
from . import search_views
from . import ai_views
app_name = 'video'

urlpatterns = [
    # MEDIA
    path("api/list-home/", views.ListMediaApiView.as_view(), name='media-home'),
    path("api/v1/feed/next/", views.RecommendationFeedApiView.as_view(), name='feed-next'),
    path("api/create-view/", views.CreateViewApiView.as_view(), name='create-view'),
    path("api/videos/track-event/", views.VideoEventView.as_view(), name='track-video-event'),
    path("api/create-comment/", views.CreateCommentApiView.as_view(), name='create-comment'),
    path("api/create-like/", views.CreateLikeApiView.as_view(), name='create-like'),
    path("api/get-comments/<str:videoId>/", views.GetCommentsApiView.as_view(), name='get-comments'),
    path("api/create-follower/", views.CreateFollowerApiView.as_view(), name="create-follower"),
    path("api/followers/<str:username>/", views.FollowersListView.as_view(), name="followers-list"),
    path("api/following/<str:username>/", views.FollowingListView.as_view(), name="following-list"),
    path("api/suggestions/<str:username>/", views.UserSuggestionsView.as_view(), name="suggestions-list"),
    
    # AI CONTENT GENERATION
    path("api/ai/generate/", ai_views.AIGenerateView.as_view(), name='ai-generate'),
    path("api/ai/styles/", ai_views.ListAIStylesView.as_view(), name='ai-styles'),
    path("api/ai/history/", ai_views.ListAIGenerationHistoryView.as_view(), name='ai-history'),
    path("api/ai/publish/", ai_views.PublishAIContentView.as_view(), name='ai-publish'),

    # SEARCH
    path("api/search/global/", search_views.GlobalSearchView.as_view(), name="global-search"),
    path("api/search/trending/", search_views.TrendingListView.as_view(), name="trending-search"),
    path("api/search/recent/", search_views.RecentSearchView.as_view(), name="recent-search"),

    # HISTORY
    path("api/stories/create/", views.CreateStoryApiView.as_view()),
    path("api/stories/like/", views.CreateStoryLikeView.as_view()),
    path("api/stories/send-story-gifted/", views.CreateGiftStoryView.as_view(), name="send-gift"),
    path("api/videos/send-video-gifted/", views.CreateGiftVideoView.as_view(), name="send-video-gift"),
    path("api/stories/gift/active/", views.ListGiftActiveApiView.as_view()),
    path("api/stories/gift/get-one/active/<int:gift_uuid>/<str:story_uuid>/", views.GetOneGiftActiveApiView.as_view()),
    path("api/stories/gift/recived/<int:story_id>/", views.ListGiftRecivedApiView.as_view()),
    path("api/stories/gift/recived/<int:story_id>/by-user/", views.ListGiftRecivedByUserApiView.as_view()),
    path("api/stories/active/", views.ListActiveStoriesApiView.as_view()),
    path("api/stories/user/<int:user_id>/", views.UserStoriesApiView.as_view()),
    path("api/stories/view/", views.ViewStoryApiView.as_view()),
    path("api/stories/<str:story_uuid>/viewers/", views.StoryViewersApiView.as_view()),
    path("api/stories/<str:uuid>/delete/", views.DeleteStoryApiView.as_view()),

    # MESSAGES
    path('api/chats/', views.ChatListView.as_view(), name='chat-list'),
    path('api/chats/<str:chat_uuid>/messages/', views.ChatMessagesView.as_view(), name='chat-messages'),
    path('api/chats/send/', views.SendMessageView.as_view(), name='send-message'),
    path('api/chats/<str:chat_uuid>/read/', views.MarkChatAsReadView.as_view(), name='mark-read'),
    path('api/update-online-status/', views.UpdateOnlineStatusView.as_view(), name='update-online-status'),
    path('api/social/connections/', views.UserConnectionsListView.as_view(), name='social-connections'),
    path('api/messages/reaction/', views.SaveMessageReactionView.as_view(), name='save-reaction'),
    path('api/v1/users/update-device-token/', views.UpdateDeviceTokenView.as_view(), name='update-device-token'),
]
