from django import forms
from django.contrib import admin
from django.utils.html import format_html
from django_ckeditor_5.widgets import CKEditor5Widget

from .models import BlogPost, ContactSubmission


class BlogPostAdminForm(forms.ModelForm):
    class Meta:
        model = BlogPost
        fields = "__all__"
        widgets = {
            "content": CKEditor5Widget(config_name="blog"),
        }


@admin.register(BlogPost)
class BlogPostAdmin(admin.ModelAdmin):
    form = BlogPostAdminForm
    list_display = ("title", "author_name", "category", "published_at", "featured", "is_published")
    list_filter = ("category", "featured", "is_published", "published_at")
    prepopulated_fields = {"slug": ("title",)}
    search_fields = ("title", "excerpt", "author_name", "meta_title", "meta_description")
    readonly_fields = ("cover_image_preview", "created_at", "updated_at")
    fieldsets = (
        (
            "Article Details",
            {
                "fields": (
                    "title",
                    "slug",
                    "excerpt",
                    "category",
                    "cover_image",
                    "cover_image_preview",
                )
            },
        ),
        (
            "Content",
            {
                "fields": ("content",),
                "classes": ("wide",),
            },
        ),
        (
            "SEO",
            {
                "fields": ("author_name", "meta_title", "meta_description"),
                "description": "Set article author and search metadata. Blank SEO fields fall back to the article title and excerpt.",
            },
        ),
        (
            "Publishing",
            {
                "fields": (
                    "published_at",
                    "read_time_minutes",
                    "featured",
                    "is_published",
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )

    def cover_image_preview(self, obj):
        image_name = getattr(obj.cover_image, "name", "") or ""
        if not image_name:
            return "No cover image uploaded yet."

        if "/" not in image_name and not image_name.startswith(("http://", "https://")):
            return format_html("Using bundled frontend fallback key: <code>{}</code>", image_name)

        try:
            image_url = obj.cover_image.url
        except ValueError:
            return "Uploaded image could not be previewed."

        return format_html(
            '<img src="{}" alt="{}" style="max-width: 320px; border-radius: 16px; box-shadow: 0 12px 32px rgba(15, 23, 42, 0.16);" />',
            image_url,
            obj.title,
        )

    cover_image_preview.short_description = "Cover Image Preview"


@admin.register(ContactSubmission)
class ContactSubmissionAdmin(admin.ModelAdmin):
    list_display = ("name", "phone", "whatsapp", "service", "city", "preferred_date", "created_at")
    list_filter = ("service", "city", "created_at")
    search_fields = ("name", "email", "phone", "whatsapp", "service", "city", "subject", "message")
