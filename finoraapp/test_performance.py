"""Tests for the service performance report."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .analytics_models import AnalyticsEvent
from .analytics_performance import (
    Catalogue,
    _titles_from_js,
    performance_report,
    reset_catalogue,
    split_path,
)
from . import analytics_performance


class SlugParsingTests(TestCase):
    """The path splitter, which has to handle hyphens on both sides."""

    def setUp(self):
        analytics_performance._CATALOGUE = Catalogue(
            services={
                "sand-supply": "Sand Supply",
                "cement-steel-supply": "Cement & Steel Supply",
                "interior-design": "Interior Design",
            },
            places={
                "kannur": "Kannur",
                "alappuzha": "Alappuzha",
                "alappuzha-town": "Alappuzha Town",
                "cherthala": "Cherthala",
                "trivandrum": "Trivandrum",
            },
        )

    def tearDown(self):
        reset_catalogue()

    def test_splits_a_service_and_town_slug(self):
        self.assertEqual(split_path("/sand-supply-cherthala"), ("Sand Supply", "Cherthala"))

    def test_prefers_the_longest_place_match(self):
        # "alappuzha-town" ends with "alappuzha". A shortest-first match would
        # report the district and leave "cement-steel-supply-alappuzha" as the
        # service, which is not a service at all.
        self.assertEqual(
            split_path("/cement-steel-supply-alappuzha-town"),
            ("Cement & Steel Supply", "Alappuzha Town"),
        )

    def test_handles_section_pages(self):
        self.assertEqual(split_path("/construction/interior-design"), ("Interior Design", None))
        self.assertEqual(split_path("/rentals/trivandrum"), ("Furniture Rental", "Trivandrum"))
        self.assertEqual(split_path("/locations/kannur"), (None, "Kannur"))

    def test_ignores_pages_with_no_service(self):
        self.assertEqual(split_path("/"), (None, None))
        self.assertEqual(split_path("/blog/a-post"), (None, None))

    def test_unknown_service_still_reports_the_place(self):
        # The 36 local template pages (ac-repair, tv-repair) are not in the
        # construction catalogue but still belong to a town.
        service, place = split_path("/ac-repair-kannur")
        self.assertEqual(place, "Kannur")
        self.assertTrue(service)


class CatalogueScopingTests(TestCase):
    """Services and districts live in one file with the same shape."""

    SAMPLE = '''
export const constructionDistricts = [
  {
    slug: "kannur",
    name: "Kannur",
  },
];

export const constructionCategories = [
  {
    slug: "sand-supply",
    // A comment between slug and name, which the real files have.
    name: "Sand Supply",
  },
];
'''

    def test_reads_only_the_named_export(self):
        services = _titles_from_js(self.SAMPLE, "constructionCategories")
        places = _titles_from_js(self.SAMPLE, "constructionDistricts")

        # An unscoped scan reported Kannur as a service, which put a district
        # at the top of the service league table.
        self.assertEqual(services, {"sand-supply": "Sand Supply"})
        self.assertEqual(places, {"kannur": "Kannur"})

    def test_missing_export_is_empty_not_an_error(self):
        self.assertEqual(_titles_from_js(self.SAMPLE, "notThere"), {})


class PerformanceReportTests(TestCase):
    def setUp(self):
        analytics_performance._CATALOGUE = Catalogue(
            services={"sand-supply": "Sand Supply", "interior-design": "Interior Design"},
            places={"kannur": "Kannur", "cherthala": "Cherthala"},
        )
        self.since = timezone.now() - timedelta(days=30)

    def tearDown(self):
        reset_catalogue()

    def _view(self, path, visitor):
        AnalyticsEvent.objects.create(
            kind=AnalyticsEvent.Kind.PAGE_VIEW, path=path, visitor_id=visitor
        )

    def _call(self, path, visitor):
        AnalyticsEvent.objects.create(
            kind=AnalyticsEvent.Kind.CLICK,
            target_type=AnalyticsEvent.Target.PHONE,
            path=path,
            visitor_id=visitor,
        )

    def test_counts_a_call_as_an_enquiry(self):
        # Most customers here call rather than fill the form. Counting forms
        # alone would report this page as dead.
        self._view("/sand-supply-cherthala", "v1")
        self._call("/sand-supply-cherthala", "v1")

        report = performance_report(self.since, min_views=1)
        sand = next(r for r in report["by_service"] if r["label"] == "Sand Supply")

        self.assertEqual(sand["enquiries"], 1)
        self.assertEqual(sand["rate"], 100.0)
        self.assertEqual(report["dead_pages"], [])

    def test_lists_a_page_with_traffic_and_no_enquiry(self):
        for i in range(6):
            self._view("/interior-design-kannur", f"v{i}")

        report = performance_report(self.since, min_views=5)

        self.assertEqual(len(report["dead_pages"]), 1)
        self.assertEqual(report["dead_pages"][0]["path"], "/interior-design-kannur")
        self.assertEqual(report["dead_pages"][0]["service"], "Interior Design")
        self.assertEqual(report["dead_pages"][0]["place"], "Kannur")

    def test_ignores_a_page_nobody_really_visited(self):
        # One view and no enquiry says nothing, so it must not be listed as a
        # page to rewrite.
        self._view("/interior-design-kannur", "v1")

        report = performance_report(self.since, min_views=5)
        self.assertEqual(report["dead_pages"], [])

    def test_groups_several_pages_under_one_service(self):
        self._view("/sand-supply-cherthala", "v1")
        self._view("/sand-supply-kannur", "v2")
        self._call("/sand-supply-kannur", "v2")

        report = performance_report(self.since, min_views=1)
        sand = next(r for r in report["by_service"] if r["label"] == "Sand Supply")

        self.assertEqual(sand["pages"], 2)
        self.assertEqual(sand["views"], 2)
        self.assertEqual(sand["enquiries"], 1)
        self.assertEqual(sand["rate"], 50.0)

    def test_survives_a_missing_frontend(self):
        # On a backend-only deploy the data files are absent. The report must
        # still return page rows rather than raising.
        analytics_performance._CATALOGUE = Catalogue()
        self._view("/sand-supply-cherthala", "v1")

        report = performance_report(self.since, min_views=1)

        self.assertFalse(report["catalogue_loaded"])
        self.assertEqual(report["by_service"], [])


class DashboardRendersTests(TestCase):
    def test_dashboard_renders_the_performance_panels(self):
        User = get_user_model()
        User.objects.create_superuser("admin", "a@b.c", "pw-for-test-only")
        self.client.login(username="admin", password="pw-for-test-only")

        AnalyticsEvent.objects.create(
            kind=AnalyticsEvent.Kind.PAGE_VIEW, path="/sand-supply-cherthala", visitor_id="v1"
        )

        response = self.client.get(reverse("admin:analytics-dashboard"))
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        for heading in ("Service performance", "Performance by location",
                        "Best performing pages", "Pages with visitors but no enquiries"):
            self.assertIn(heading, body)
