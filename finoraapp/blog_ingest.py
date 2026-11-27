"""Authenticated endpoint for a scheduled agent to file blog drafts.

The cloud agent that writes scheduled posts runs outside this server and
cannot reach the database, so it posts finished drafts here instead.

Everything this endpoint accepts becomes a page on a live site, so it is
deliberately narrow:

  * a shared token, compared in constant time, and the endpoint is simply
    absent when no token is configured — a missing secret must never mean
    "open to everyone"
  * posts are always created unpublished; the endpoint cannot publish
  * the token cannot edit or delete an existing post, only add a draft
  * rate limited, so a leaked token cannot fill the blog in one night
"""

from __future__ import annotations

import hmac
import logging

from django.conf import settings
from django.utils import timezone
from django.utils.text import slugify
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .models import BlogPost

logger = logging.getLogger(__name__)


class BlogDraftSerializer(serializers.ModelSerializer):
    # The model's slug is unique, so the default validator would reject a
    # clash outright. A clash is expected here — the same topic can come round
    # again — and the view suffixes it rather than failing the whole post.
    slug = serializers.CharField(max_length=255, required=False, allow_blank=True)

    class Meta:
        model = BlogPost
        fields = [
            "title", "slug", "excerpt", "category", "content",
            "meta_title", "meta_description", "read_time_minutes",
        ]

    def validate_content(self, value):
        # A near-empty post is a thin page, which is the opposite of the point.
        if len(value.strip()) < 400:
            raise serializers.ValidationError(
                "content is too short to publish; write at least a few hundred words"
            )
        return value


class BlogDraftIngestView(APIView):
    """POST a finished post; it is stored as a draft for review.

    Returns 404 rather than 401 when no token is configured, so the endpoint
    does not advertise itself on a deployment that never enabled it.
    """

    authentication_classes = []
    permission_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "blog_ingest"

    def post(self, request):
        expected = getattr(settings, "BLOG_INGEST_TOKEN", "")
        if not expected:
            # Not configured means not available, never means unprotected.
            return Response(status=status.HTTP_404_NOT_FOUND)

        supplied = request.headers.get("X-Ingest-Token", "")
        if not hmac.compare_digest(supplied, expected):
            logger.warning("blog ingest rejected: bad or missing token")
            return Response(
                {"detail": "Invalid token."}, status=status.HTTP_403_FORBIDDEN
            )

        serializer = BlogDraftSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data
        slug = self._unique_slug(data.get("slug") or slugify(data["title"]))

        post = BlogPost.objects.create(
            **{**data, "slug": slug},
            published_at=timezone.now().date(),
            # Never publishable through this endpoint. A token that could put
            # text straight onto the site is a much larger thing to leak.
            is_published=False,
        )

        logger.info("blog draft filed: %s", post.slug)
        return Response(
            {"slug": post.slug, "is_published": False},
            status=status.HTTP_201_CREATED,
        )

    @staticmethod
    def _unique_slug(base: str) -> str:
        base = (base or "post")[:240]
        slug = base
        suffix = 2
        while BlogPost.objects.filter(slug=slug).exists():
            slug = f"{base}-{suffix}"
            suffix += 1
        return slug
