import re

from django.conf import settings
from rest_framework import serializers
from django.utils.text import Truncator

from .models import BlogPost, ContactSubmission


MEDIA_ATTRIBUTE_PATTERN = re.compile(
    r'(?P<attr>(?:src|href))=(?P<quote>["\'])(?P<url>(?:/)?media/[^"\']+)(?P=quote)'
)


def format_publish_date(value):
    return f"{value.strftime('%B')} {value.day}, {value.year}"


def build_media_url(request, value):
    if not value:
        return ""

    if value.startswith(("http://", "https://")):
        return value

    if value.startswith("/"):
        return request.build_absolute_uri(value) if request else value

    if "/" not in value and not value.startswith("media/"):
        return value

    media_path = value if value.startswith("media/") else f"{settings.MEDIA_URL.rstrip('/')}/{value.lstrip('/')}"
    normalized_path = media_path if media_path.startswith("/") else f"/{media_path}"
    return request.build_absolute_uri(normalized_path) if request else normalized_path


def absolutize_media_references(request, html):
    if not request or not html:
        return html

    def replace(match):
        media_url = match.group("url")
        normalized_url = media_url if media_url.startswith("/") else f"/{media_url}"
        absolute_url = request.build_absolute_uri(normalized_url)
        return f'{match.group("attr")}={match.group("quote")}{absolute_url}{match.group("quote")}'

    return MEDIA_ATTRIBUTE_PATTERN.sub(replace, html)


class BlogPostListSerializer(serializers.ModelSerializer):
    cover_image = serializers.SerializerMethodField()
    published_label = serializers.SerializerMethodField()
    read_time_label = serializers.SerializerMethodField()

    class Meta:
        model = BlogPost
        fields = (
            "slug",
            "title",
            "excerpt",
            "category",
            "cover_image",
            "featured",
            "published_at",
            "published_label",
            "read_time_minutes",
            "read_time_label",
            "author_name",
        )

    def get_published_label(self, obj):
        return format_publish_date(obj.published_at)

    def get_read_time_label(self, obj):
        return f"{obj.read_time_minutes} min read"

    def get_cover_image(self, obj):
        request = self.context.get("request")
        image_name = getattr(obj.cover_image, "name", "") or ""
        return build_media_url(request, image_name)


class BlogPostDetailSerializer(BlogPostListSerializer):
    content = serializers.SerializerMethodField()
    meta_title = serializers.SerializerMethodField()
    meta_description = serializers.SerializerMethodField()

    class Meta(BlogPostListSerializer.Meta):
        fields = BlogPostListSerializer.Meta.fields + (
            "content",
            "meta_title",
            "meta_description",
        )

    def get_meta_title(self, obj):
        return obj.meta_title or obj.title

    def get_meta_description(self, obj):
        return obj.meta_description or Truncator(obj.excerpt).chars(160)

    def get_content(self, obj):
        request = self.context.get("request")
        return absolutize_media_references(request, obj.content)


class ContactSubmissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContactSubmission
        fields = (
            "id",
            "name",
            "email",
            "phone",
            "whatsapp",
            "service",
            "city",
            "preferred_date",
            "subject",
            "message",
            "created_at",
        )
        read_only_fields = ("id", "created_at")

    def to_internal_value(self, data):
        cleaned = {
            field: value.strip() if isinstance(value, str) else value
            for field, value in data.items()
        }
        return super().to_internal_value(cleaned)

    def validate(self, attrs):
        for field in ("name", "phone", "service", "city"):
            if not attrs.get(field):
                raise serializers.ValidationError({field: "This field may not be blank."})

        if not attrs.get("subject"):
            attrs["subject"] = f"New {attrs['service']} booking in {attrs['city']}"

        return attrs
