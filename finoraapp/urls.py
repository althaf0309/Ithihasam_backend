from django.urls import path

from .views import BlogPostDetailAPIView, BlogPostListAPIView, ContactSubmissionCreateAPIView, HealthCheckAPIView

urlpatterns = [
    path("health/", HealthCheckAPIView.as_view(), name="health-check"),
    path("blog/", BlogPostListAPIView.as_view(), name="blog-list"),
    path("blog/<slug:slug>/", BlogPostDetailAPIView.as_view(), name="blog-detail"),
    path("contact/", ContactSubmissionCreateAPIView.as_view(), name="contact-create"),
]
