"""Tests for the token-guarded blog draft endpoint.

Everything this endpoint accepts becomes a page on a live site, so the
security properties are tested as carefully as the happy path.
"""

from django.test import TestCase, override_settings
from django.urls import reverse

from .models import BlogPost

TOKEN = "test-token-not-a-real-secret-0123456789"

GOOD_POST = {
    "title": "Sand Supply in Cherthala",
    "slug": "sand-supply-cherthala-cost",
    "excerpt": "What a load of sand costs in Cherthala.",
    "category": "Materials",
    "content": "## Ground conditions\n\n" + ("Sandy soil needs wider footings. " * 40),
    "meta_title": "Sand Supply in Cherthala",
    "meta_description": "What a load of sand costs in Cherthala and what changes it.",
    "read_time_minutes": 5,
}


@override_settings(BLOG_INGEST_TOKEN=TOKEN)
class BlogIngestTests(TestCase):
    def setUp(self):
        self.url = reverse("blog-draft-ingest")
        self.before = set(BlogPost.objects.values_list("id", flat=True))

    def _new(self):
        return BlogPost.objects.exclude(id__in=self.before)

    def _post(self, data=None, token=TOKEN, **extra):
        headers = {"HTTP_X_INGEST_TOKEN": token} if token is not None else {}
        return self.client.post(
            self.url,
            data if data is not None else GOOD_POST,
            content_type="application/json",
            **headers,
            **extra,
        )

    # --------------------------------------------------------------- auth

    def test_a_valid_token_files_a_draft(self):
        response = self._post()

        self.assertEqual(response.status_code, 201)
        self.assertEqual(self._new().count(), 1)

    def test_no_token_is_rejected(self):
        response = self._post(token=None)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(self._new().count(), 0)

    def test_a_wrong_token_is_rejected(self):
        response = self._post(token="wrong-token-entirely")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(self._new().count(), 0)

    def test_an_almost_right_token_is_rejected(self):
        # Guards the constant-time comparison against a prefix match.
        response = self._post(token=TOKEN[:-1])

        self.assertEqual(response.status_code, 403)
        self.assertEqual(self._new().count(), 0)

    @override_settings(BLOG_INGEST_TOKEN="")
    def test_an_unconfigured_token_closes_the_endpoint(self):
        # A missing secret must never mean "open to everyone". 404 rather than
        # 403 so the endpoint does not advertise itself where it is unused.
        response = self._post(token=None)

        self.assertEqual(response.status_code, 404)
        self.assertEqual(self._new().count(), 0)

    @override_settings(BLOG_INGEST_TOKEN="")
    def test_an_unconfigured_token_is_closed_even_with_a_token(self):
        response = self._post(token="anything")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(self._new().count(), 0)

    # ------------------------------------------------------------- limits

    def test_a_filed_post_is_never_published(self):
        # A token that could put text straight onto the site is a much larger
        # thing to leak than one that can only queue a draft.
        self._post()
        self.assertFalse(self._new().get().is_published)

    def test_the_caller_cannot_publish_by_asking(self):
        response = self._post({**GOOD_POST, "is_published": True})

        self.assertEqual(response.status_code, 201)
        self.assertFalse(self._new().get().is_published)

    def test_the_caller_cannot_overwrite_an_existing_post(self):
        existing = BlogPost.objects.create(
            title="Existing", slug="sand-supply-cherthala-cost", excerpt="x",
            category="Materials", content="x" * 500, published_at="2026-01-01",
            is_published=True,
        )

        response = self._post()

        self.assertEqual(response.status_code, 201)
        existing.refresh_from_db()
        self.assertEqual(existing.title, "Existing")
        self.assertTrue(existing.is_published)
        # The new one got a suffixed slug rather than replacing it.
        self.assertTrue(self._new().filter(slug="sand-supply-cherthala-cost-2").exists())

    def test_a_thin_post_is_rejected(self):
        response = self._post({**GOOD_POST, "content": "Too short."})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(self._new().count(), 0)

    def test_a_missing_title_is_rejected(self):
        payload = {k: v for k, v in GOOD_POST.items() if k != "title"}
        response = self._post(payload)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(self._new().count(), 0)

    def test_get_is_not_allowed(self):
        response = self.client.get(self.url, HTTP_X_INGEST_TOKEN=TOKEN)
        self.assertEqual(response.status_code, 405)
