from django.urls import path
from .views import FeedbackList

urlpatterns = [path("feedback/", FeedbackList.as_view(), name="feedback-list")]
