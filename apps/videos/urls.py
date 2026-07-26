from django.urls import path
from . import views
from . import search_views
from . import ai_views
app_name = 'video'

urlpatterns = [
    # MEDIA
    path("api/list-home/", views.ListMediaApiView.as_view(), name='media-home'),
    path("api/videos/user/<str:username>/", views.UserVideosApiView.as_view(), name='user-videos'),
    path("api/videos/create/", views.VideoUploadAPIView.as_view(), name='video-upload'),
    path('api/videos/saved/', views.SavedVideoView.as_view(), name='saved-videos'),
    path("api/videos/track-event/", views.VideoEventView.as_view(), name='track-video-event'),
    path("api/videos/send-video-gifted/", views.CreateGiftVideoView.as_view(), name="send-video-gift"),
    path("api/videos/gifts/received/", views.ListVideoGiftsReceivedView.as_view()),
    path("api/videos/gifts/mark-seen/", views.MarkVideoGiftsSeenView.as_view()),
    path("api/create-view/", views.CreateViewApiView.as_view(), name='create-view'),
    path("api/create-comment/", views.CreateCommentApiView.as_view(), name='create-comment'),
    path("api/create-like/", views.CreateLikeApiView.as_view(), name='create-like'),
    path("api/get-comments/<str:videoId>/", views.GetCommentsApiView.as_view(), name='get-comments'),
    path("api/create-follower/", views.CreateFollowerApiView.as_view(), name="create-follower"),
    path("api/followers/<str:username>/", views.FollowersListView.as_view(), name="followers-list"),
    path("api/following/<str:username>/", views.FollowingListView.as_view(), name="following-list"),
    path("api/suggestions/<str:username>/", views.UserSuggestionsView.as_view(), name="suggestions-list"),
    # NOTE: esta URL con parámetro dinámico va AL FINAL para no capturar rutas específicas
    path("api/videos/<str:uuid>/", views.VideoDetailApiView.as_view(), name='video-detail'),
    
    # AI CONTENT GENERATION
    path("api/ai/generate/", ai_views.AIGenerateView.as_view(), name='ai-generate'),
    path("api/ai/status/<int:history_id>/", ai_views.AIGenerationStatusView.as_view(), name='ai-status'),
    path("api/ai/styles/", ai_views.ListAIStylesView.as_view(), name='ai-styles'),
    path("api/ai/history/", ai_views.ListAIGenerationHistoryView.as_view(), name='ai-history'),
    path("api/ai/publish/", ai_views.PublishAIContentView.as_view(), name='ai-publish'),
    path("api/ai/credits/", ai_views.AICreditsView.as_view(), name='ai-credits'),
    path("api/ai/packages/", ai_views.AIPackageListView.as_view(), name='ai-packages'),
    path("api/ai/packages/purchase/", ai_views.AIPackagePurchaseView.as_view(), name='ai-packages-purchase'),
    path("api/ai/packages/checkout/", ai_views.AIPackageCheckoutView.as_view(), name='ai-packages-checkout'),
    path("api/ai/packages/checkout/verify/", ai_views.AIPackageCheckoutVerifyView.as_view(), name='ai-packages-checkout-verify'),

    # SEARCH
    path("api/search/global/", search_views.GlobalSearchView.as_view(), name="global-search"),
    path("api/search/trending/", search_views.TrendingListView.as_view(), name="trending-search"),
    path("api/search/recent/", search_views.RecentSearchView.as_view(), name="recent-search"),

    # HISTORY
    path("api/stories/create/", views.CreateStoryApiView.as_view()),
    path("api/stories/like/", views.CreateStoryLikeView.as_view()),
    path("api/stories/send-story-gifted/", views.CreateGiftStoryView.as_view(), name="send-gift"),
    path("api/stories/gift/active/", views.ListGiftActiveApiView.as_view()),
    path("api/stories/gift/get-one/active/<int:gift_uuid>/<str:story_uuid>/", views.GetOneGiftActiveApiView.as_view()),
    path("api/stories/gift/recived/<int:story_id>/", views.ListGiftRecivedApiView.as_view()),
    path("api/stories/gift/recived/<int:story_id>/by-user/", views.ListGiftRecivedByUserApiView.as_view()),
    path("api/users/send-user-gift/", views.CreateGiftUserView.as_view(), name="send-user-gift"),
    path("api/users/gifts/received/", views.ListUserGiftsReceivedView.as_view(), name="user-gifts-received"),
    path("api/users/gifts/mark-seen/", views.MarkUserGiftsSeenView.as_view(), name="user-gifts-mark-seen"),
    path("api/stories/gifts/mark-seen/", views.MarkStoryGiftSeenView.as_view(), name="story-gifts-mark-seen"),
    path("api/stories/active/", views.ListActiveStoriesApiView.as_view()),
    path("api/stories/by-media/<str:media_ref>/", views.StoryDetailByMediaApiView.as_view()),
    path("api/stories/user/<int:user_id>/", views.UserStoriesApiView.as_view()),
    path("api/stories/view/", views.ViewStoryApiView.as_view()),
    path("api/stories/<str:story_uuid>/viewers/", views.StoryViewersApiView.as_view()),
    path("api/stories/<str:uuid>/delete/", views.DeleteStoryApiView.as_view()),
    path("api/stories/<str:uuid>/report/", views.ReportStoryApiView.as_view()),

    # MESSAGES
    path('api/chats/', views.ChatListView.as_view(), name='chat-list'),
    path('api/chats/<str:chat_uuid>/messages/', views.ChatMessagesView.as_view(), name='chat-messages'),
    path('api/chats/send/', views.SendMessageView.as_view(), name='send-message'),
    path('api/chats/<str:chat_uuid>/read/', views.MarkChatAsReadView.as_view(), name='mark-read'),
    path('api/chats/<str:chat_uuid>/folder/', views.UpdateChatFolderView.as_view(), name='update-folder'),
    path('api/chats/<str:chat_uuid>/search/', views.SearchMessagesView.as_view(), name='search-messages'),
    path('api/chats/<str:chat_uuid>/read-messages/', views.MarkMessagesReadView.as_view(), name='mark-messages-read'),
    path('api/messages/<str:msg_uuid>/delete/', views.DeleteMessageView.as_view(), name='delete-message'),
    path('api/messages/<str:msg_uuid>/edit/', views.EditMessageView.as_view(), name='edit-message'),
    path('api/messages/forward/', views.ForwardMessageView.as_view(), name='forward-message'),
    path('api/update-online-status/', views.UpdateOnlineStatusView.as_view(), name='update-online-status'),
    path('api/social/connections/', views.UserConnectionsListView.as_view(), name='social-connections'),
    path('api/v1/users/update-device-token/', views.UpdateDeviceTokenView.as_view(), name='update-device-token'),

    # NOTIFICATIONS
    path('api/notifications/', views.NotificationListView.as_view(), name='notifications-list'),
    path('api/notifications/read/', views.NotificationMarkReadView.as_view(), name='notifications-read'),
    path('api/notifications/unread-count/', views.NotificationUnreadCountView.as_view(), name='notifications-unread'),

    # AUDIO TRACKS
    path('api/audio-tracks/', views.AudioTrackListView.as_view(), name='audio-tracks'),
    path('api/favorite-tracks/', views.FavoriteTrackView.as_view(), name='favorite-tracks'),
    path('api/hashtags/search/', views.HashtagSearchView.as_view(), name='hashtag-search'),
]
