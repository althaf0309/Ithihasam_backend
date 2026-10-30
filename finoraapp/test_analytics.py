"""Tests for visitor analytics ingest, bot filtering, dedupe and the dashboard."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .analytics_geo import is_bot, parse_device
from .analytics_models import AnalyticsEvent

BROWSER_UA = (
    "Mozilla/5.0 (Linux; Android 13; SM-G991B) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Mobile Safari/537.36"
)


def click(**overrides):
    payload = {
        "kind": "click",
        "visitor_id": "visitor-1",
        "path": "/services/appliance-servicing",
        "label": "Call Now",
        "href": "tel:+919400096518",
        "target_type": "phone",
    }
    payload.update(overrides)
    return payload


class AnalyticsIngestTests(TestCase):
    url = "/api/analytics/events/"

    def post(self, events, agent=BROWSER_UA):
        return self.client.post(
            self.url,
            data={"events": events},
            content_type="application/json",
            HTTP_USER_AGENT=agent,
        )

    def test_records_a_click(self):
        response = self.post([click()])

        self.assertEqual(response.status_code, 204)
        event = AnalyticsEvent.objects.get()
        self.assertEqual(event.target_type, AnalyticsEvent.Target.PHONE)
        self.assertEqual(event.label, "Call Now")
        self.assertEqual(event.repeat_index, 1)

    def test_ignores_bots(self):
        """Crawlers would otherwise dominate the numbers."""
        response = self.post([click()], agent="Mozilla/5.0 (compatible; Googlebot/2.1)")

        self.assertEqual(response.status_code, 204)
        self.assertEqual(AnalyticsEvent.objects.count(), 0)

    def test_ignores_requests_without_a_user_agent(self):
        self.post([click()], agent="")
        self.assertEqual(AnalyticsEvent.objects.count(), 0)

    def test_headless_browsers_are_not_treated_as_bots(self):
        """Browser tests run headless; filtering them records nothing."""
        headless = "Mozilla/5.0 (X11; Linux x86_64) HeadlessChrome/120.0 Safari/537.36"

        self.assertFalse(is_bot(headless))
        self.post([click()], agent=headless)
        self.assertEqual(AnalyticsEvent.objects.count(), 1)

    def test_double_tap_within_two_seconds_is_stored_once(self):
        self.post([click()])
        self.post([click()])

        self.assertEqual(AnalyticsEvent.objects.count(), 1)

    def test_later_click_is_kept_and_numbered(self):
        """A genuine second attempt is signal, not noise."""
        self.post([click()])
        AnalyticsEvent.objects.update(created_at=timezone.now() - timedelta(minutes=5))

        self.post([click()])

        self.assertEqual(AnalyticsEvent.objects.count(), 2)
        self.assertEqual(AnalyticsEvent.objects.order_by("created_at").last().repeat_index, 2)

    def test_different_visitors_do_not_deduplicate_each_other(self):
        self.post([click(visitor_id="a")])
        self.post([click(visitor_id="b")])

        self.assertEqual(AnalyticsEvent.objects.count(), 2)

    def test_rejects_unknown_kind_without_failing(self):
        response = self.post([click(kind="not_a_kind")])

        self.assertEqual(response.status_code, 204)
        self.assertEqual(AnalyticsEvent.objects.count(), 0)

    def test_requires_a_visitor_id(self):
        self.post([click(visitor_id="")])
        self.assertEqual(AnalyticsEvent.objects.count(), 0)

    def test_unknown_target_type_falls_back_to_other(self):
        self.post([click(target_type="telepathy")])
        self.assertEqual(AnalyticsEvent.objects.get().target_type, AnalyticsEvent.Target.OTHER)

    def test_records_a_form_submission(self):
        self.post([{
            "kind": "form_submit",
            "visitor_id": "visitor-9",
            "path": "/contact",
            "form_service": "Painting Services",
            "form_city": "Thalassery",
            "form_succeeded": True,
        }])

        event = AnalyticsEvent.objects.get()
        self.assertEqual(event.kind, AnalyticsEvent.Kind.FORM_SUBMIT)
        self.assertEqual(event.form_service, "Painting Services")
        self.assertTrue(event.form_succeeded)

    def test_stores_no_ip_address(self):
        """Privacy: the IP is resolved in memory and never persisted."""
        self.post([click()], agent=BROWSER_UA)

        stored = AnalyticsEvent.objects.values().get()
        self.assertNotIn("ip", " ".join(stored.keys()).lower())
        self.assertFalse(any("127.0.0.1" in str(value) for value in stored.values()))

    def test_caps_events_per_request(self):
        self.post([click(label=f"Button {index}") for index in range(40)])
        self.assertLessEqual(AnalyticsEvent.objects.count(), 20)


class DeviceParsingTests(TestCase):
    def test_detects_mobile(self):
        self.assertEqual(parse_device(BROWSER_UA)["device_type"], "mobile")

    def test_detects_desktop_and_browser(self):
        parsed = parse_device(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        )
        self.assertEqual(parsed["device_type"], "desktop")
        self.assertEqual(parsed["browser"], "Chrome")
        self.assertEqual(parsed["os"], "Windows")


class AnalyticsDashboardTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_superuser("owner", "owner@example.com", "pw-12345")
        AnalyticsEvent.objects.create(
            kind=AnalyticsEvent.Kind.CLICK,
            visitor_id="v1",
            path="/",
            label="Call Now",
            target_type=AnalyticsEvent.Target.PHONE,
            city="Thalassery",
            country="India",
        )

    def test_dashboard_requires_staff_login(self):
        response = self.client.get(reverse("admin:analytics-dashboard"))
        self.assertIn(response.status_code, (302, 403))

    def test_dashboard_renders_for_staff(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("admin:analytics-dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Call taps")

    def test_csv_export_neutralises_formula_injection(self):
        AnalyticsEvent.objects.create(
            kind=AnalyticsEvent.Kind.CLICK,
            visitor_id="v2",
            path="/",
            label="=HYPERLINK(\"http://evil\",\"click\")",
            target_type=AnalyticsEvent.Target.OTHER,
        )
        self.client.force_login(self.staff)

        body = self.client.get(reverse("admin:analytics-export")).content.decode()

        # Prefixed with an apostrophe so Excel treats it as text, not a formula.
        self.assertIn("'=HYPERLINK", body)
