from datetime import date

from django.core import mail
from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from .models import BlogPost, ContactSubmission


class FinoraApiTests(APITestCase):
    def setUp(self):
        self.post = BlogPost.objects.create(
            title="Test Blog Post",
            slug="test-blog-post",
            excerpt="A short excerpt.",
            category="Tax",
            cover_image="blog-tax",
            content="<p>Paragraph one.</p><p>Paragraph two.</p>",
            author_name="Finora Editorial",
            meta_title="Custom Meta Title",
            meta_description="Custom meta description.",
            read_time_minutes=6,
            published_at=date(2026, 4, 8),
            featured=True,
        )

    def test_blog_list_returns_seeded_shape(self):
        response = self.client.get(reverse("blog-list"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        item = next(entry for entry in response.data if entry["slug"] == self.post.slug)
        self.assertEqual(item["read_time_label"], "6 min read")

    def test_blog_detail_returns_content(self):
        response = self.client.get(reverse("blog-detail", kwargs={"slug": self.post.slug}))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["content"], self.post.content)
        self.assertEqual(response.data["meta_title"], self.post.meta_title)
        self.assertEqual(response.data["meta_description"], self.post.meta_description)
        self.assertEqual(response.data["author_name"], self.post.author_name)

    def test_blog_detail_absolutizes_embedded_media_paths(self):
        self.post.content = '<p>Guide image:</p><img src="/media/ckeditor/how-to.jpg" alt="How to" />'
        self.post.save(update_fields=["content"])

        response = self.client.get(reverse("blog-detail", kwargs={"slug": self.post.slug}))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('src="http://testserver/media/ckeditor/how-to.jpg"', response.data["content"])

    def test_blog_serializer_preserves_legacy_cover_image_keys(self):
        response = self.client.get(reverse("blog-list"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        item = next(entry for entry in response.data if entry["slug"] == self.post.slug)
        self.assertEqual(item["cover_image"], "blog-tax")

    def test_blog_serializer_returns_absolute_uploaded_cover_image_url(self):
        self.post.cover_image = "blog/covers/test-cover.jpg"
        self.post.save(update_fields=["cover_image"])

        response = self.client.get(reverse("blog-detail", kwargs={"slug": self.post.slug}))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["cover_image"], "http://testserver/media/blog/covers/test-cover.jpg")

    def test_health_check_returns_ok(self):
        response = self.client.get(reverse("health-check"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "ok")

    def test_sitemap_contains_blog_slug(self):
        response = self.client.get(reverse("sitemap-xml"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        content = response.content.decode()
        self.assertIn("/services", content)
        self.assertIn("/about", content)
        self.assertIn("/contact", content)
        self.assertIn("/locations/thalassery", content)
        self.assertIn("/locations/payyannur", content)
        self.assertIn("/locations/chakkarakkal", content)
        self.assertIn("/ac-repair-thalassery", content)
        self.assertIn("/fridge-repair-thalassery", content)
        self.assertIn("/washing-machine-repair-panoor", content)
        self.assertIn("/painting-chakkarakkal", content)
        self.assertIn("/carpentry-mahe", content)
        self.assertIn("/cctv-installation-payyannur", content)
        self.assertIn("/news/itihasam-expands-to-5-new-cities", content)
        self.assertIn("/blog/test-blog-post", response.content.decode())

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        BOOKING_NOTIFICATION_EMAILS=["ops@ithihasa.test"],
        DEFAULT_FROM_EMAIL="noreply@ithihasa.test",
    )
    def test_contact_submission_is_saved(self):
        payload = {
            "name": "Amina Noor",
            "email": "amina@example.com",
            "phone": "+919876543210",
            "whatsapp": "+919876543210",
            "service": "Deep Cleaning Services",
            "city": "Kochi",
            "preferred_date": "2026-04-20",
            "message": "Please call before arriving.",
        }

        response = self.client.post(reverse("contact-create"), payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(ContactSubmission.objects.count(), 1)
        self.assertEqual(response.data["submission"]["name"], payload["name"])
        self.assertEqual(response.data["submission"]["city"], payload["city"])
        self.assertEqual(response.data["submission"]["subject"], "New Deep Cleaning Services booking in Kochi")
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["ops@ithihasa.test"])

# Create your tests here.
