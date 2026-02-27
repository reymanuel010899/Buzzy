from django.urls import path
from . import views
app_name = 'video'

urlpatterns = [
    # MEDIA
    path("api/list-home/", views.ListMediaApiView.as_view(), name='media-home'),
    path("api/create-view/", views.CreateViewApiView.as_view(), name='create-view'),
    path("api/create-comment/", views.CreateCommentApiView.as_view(), name='create-comment'),
    path("api/create-like/", views.CreateLikeApiView.as_view(), name='create-like'),
    path("api/get-comments/<str:videoId>/", views.GetCommentsApiView.as_view(), name='get-comments'),
    path("api/create-follower/", views.CreateFollowerApiView.as_view(), name="create-follower"),

    # HISTORY
    path("api/stories/create/", views.CreateStoryApiView.as_view()),
    path("api/stories/like/", views.CreateStoryLikeView.as_view()),
    path("api/stories/send-story-gifted/", views.CreateGiftStoryView.as_view(), name="send-gift"),
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
]
