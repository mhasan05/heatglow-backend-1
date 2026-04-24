from django.urls import path
from .views import LoginView, TokenRefreshAPIView, MeView

urlpatterns = [
    path('login/', LoginView.as_view(), name='auth-login'),
    path('refresh/', TokenRefreshAPIView.as_view(), name='auth-refresh'),
    path('me/', MeView.as_view(), name='auth-me'),
]