"""Tests for visitor analytics ingest, bot filtering, dedupe and the dashboard."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .analytics_geo import is_bot, parse_device
from .analytics_models import AnalyticsEvent
from .models import ContactSubmission

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
        """The privacy policy states we do not keep IPs; this enforces it.

        The IP is read once to derive a town and then discarded, so the table
        holds no personal data under the DPDP Act.
        """
        self.post([click()], agent=BROWSER_UA)

        stored = AnalyticsEvent.objects.values().get()
        self.assertNotIn("ip_address", stored)
        self.assertFalse(
            any("127.0.0.1" in str(value) for value in stored.values()),
            "An IP address leaked into a stored field.",
        )

    def test_captures_the_name_from_a_form_submission(self):
        self.post([{
            "kind": "form_submit",
            "visitor_id": "visitor-named",
            "path": "/contact",
            "person_name": "Anjana K",
            "person_phone": "9400096518",
        }])

        event = AnalyticsEvent.objects.get()
        self.assertEqual(event.person_name, "Anjana K")

    def test_name_is_backfilled_onto_earlier_clicks(self):
        """A click before the form was anonymous; afterwards it has a person."""
        self.post([click(visitor_id="v-later")])
        self.post([{
            "kind": "form_submit",
            "visitor_id": "v-later",
            "path": "/contact",
            "person_name": "Shaji M",
            "person_phone": "9400011111",
        }])

        earlier = AnalyticsEvent.objects.get(kind=AnalyticsEvent.Kind.CLICK)
        self.assertEqual(earlier.person_name, "Shaji M")

    def test_backfill_does_not_touch_other_visitors(self):
        self.post([click(visitor_id="someone-else")])
        self.post([{
            "kind": "form_submit",
            "visitor_id": "v-named",
            "path": "/contact",
            "person_name": "Anjana K",
        }])

        other = AnalyticsEvent.objects.get(visitor_id="someone-else")
        self.assertEqual(other.person_name, "")

    def test_retention_purge_removes_old_rows(self):
        from .analytics_models import purge_expired_events

        self.post([click()])
        AnalyticsEvent.objects.update(created_at=timezone.now() - timedelta(days=400))

        self.assertEqual(purge_expired_events(), 1)
        self.assertEqual(AnalyticsEvent.objects.count(), 0)

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


class BookingNotificationTests(TestCase):
    """The outcome of the alert email must be visible, not silently lost."""

    def _submit(self):
        return self.client.post(
            "/api/contact/",
            data={
                "name": "Anjana K",
                "phone": "9400096518",
                "service": "Rental — Sofa on Rent",
                "city": "Kochi",
            },
            content_type="application/json",
        )

    @override_settings(
        BOOKING_NOTIFICATION_EMAILS=["services@ithihasam.in"],
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    )
    def test_successful_send_is_recorded(self):
        response = self._submit()

        self.assertEqual(response.status_code, 201)
        submission = ContactSubmission.objects.get()
        self.assertTrue(submission.notification_sent)
        self.assertEqual(submission.notification_error, "")
        self.assertEqual(len(mail.outbox), 1)

    @override_settings(BOOKING_NOTIFICATION_EMAILS=[])
    def test_missing_recipient_is_recorded_not_swallowed(self):
        """Without this the lead saves and nobody ever learns the email failed."""
        self._submit()

        submission = ContactSubmission.objects.get()
        self.assertFalse(submission.notification_sent)
        self.assertIn("No recipient configured", submission.notification_error)

    @override_settings(
        BOOKING_NOTIFICATION_EMAILS=["services@ithihasam.in"],
        EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
        EMAIL_HOST="smtp.invalid",
        EMAIL_TIMEOUT=1,
    )
    def test_lead_is_still_saved_when_the_email_fails(self):
        """Losing the enquiry because the mail server is down would be worse."""
        response = self._submit()

        self.assertEqual(response.status_code, 201)
        submission = ContactSubmission.objects.get()
        self.assertFalse(submission.notification_sent)
        self.assertTrue(submission.notification_error)
