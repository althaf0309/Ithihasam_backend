from django.urls import path

from .analytics_views import AnalyticsIngestAPIView
from .blog_ingest import BlogDraftIngestView
from .views import BlogPostDetailAPIView, BlogPostListAPIView, ContactSubmissionCreateAPIView, HealthCheckAPIView

urlpatterns = [
    path("analytics/events/", AnalyticsIngestAPIView.as_view(), name="analytics-ingest"),
    path("health/", HealthCheckAPIView.as_view(), name="health-check"),
    path("blog/", BlogPostListAPIView.as_view(), name="blog-list"),
    # Token-guarded; a scheduled agent files drafts here. Absent unless
    # BLOG_INGEST_TOKEN is configured.
    path("blog/drafts/", BlogDraftIngestView.as_view(), name="blog-draft-ingest"),
    path("blog/<slug:slug>/", BlogPostDetailAPIView.as_view(), name="blog-detail"),
    path("contact/", ContactSubmissionCreateAPIView.as_view(), name="contact-create"),
]
