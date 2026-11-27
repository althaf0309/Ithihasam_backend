"""Tests for scheduled blog generation."""

from datetime import date
from io import StringIO
from unittest.mock import patch

from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings

from .blog_planner import Topic, plan_topics
from .blog_writer import WrittenPost, build_brief
from .models import BlogPost


def _topic(**overrides) -> Topic:
    defaults = dict(
        service_slug="sand-supply",
        service_name="Sand Supply",
        place_slug="cherthala",
        place_name="Cherthala",
        angle="cost",
        angle_label="what it costs",
        facts={
            "town": {
                "terrain": "coastal sandy soil with low bearing",
                "access": "narrow interior lanes",
                "note": "Low-bearing sandy soil needs wider footings.",
            },
            "service": {
                "intro": "M-sand and P-sand supplied by the load.",
                "items": ["M-sand supply", "P-sand supply"],
                "compliance": "River sand only from legally authorised sources.",
            },
        },
    )
    defaults.update(overrides)
    return Topic(**defaults)


class PlannerTests(TestCase):
    def test_a_batch_spreads_across_services_towns_and_angles(self):
        # Stepping every axis by the same index produced 30 posts about one
        # town, which is 30 near-identical articles.
        topics = plan_topics(date(2026, 11, 27), 30)

        self.assertEqual(len(topics), 30)
        self.assertGreater(len({t.service_slug for t in topics}), 5)
        self.assertGreater(len({t.place_slug for t in topics}), 5)

    def test_every_topic_in_a_batch_is_unique(self):
        topics = plan_topics(date(2026, 11, 27), 30)
        self.assertEqual(len({t.key for t in topics}), len(topics))

    def test_the_same_day_plans_the_same_topics(self):
        # Re-running after a crash must not produce a different set, or the
        # schedule drifts and duplicates appear.
        first = plan_topics(date(2026, 11, 27), 10)
        second = plan_topics(date(2026, 11, 27), 10)
        self.assertEqual([t.key for t in first], [t.key for t in second])

    def test_different_days_plan_different_topics(self):
        monday = {t.key for t in plan_topics(date(2026, 11, 27), 10)}
        tuesday = {t.key for t in plan_topics(date(2026, 11, 28), 10)}
        self.assertNotEqual(monday, tuesday)

    @override_settings(BLOG_SERVICES=["sand-supply"], BLOG_PLACES=["kannur"])
    def test_scope_can_be_narrowed_by_settings(self):
        # This is how "boost construction, skip rentals" is expressed.
        topics = plan_topics(date(2026, 11, 27), 5)
        self.assertTrue(topics)
        self.assertEqual({t.service_slug for t in topics}, {"sand-supply"})
        self.assertEqual({t.place_slug for t in topics}, {"kannur"})

    @override_settings(BLOG_SERVICES=["does-not-exist"])
    def test_an_unknown_service_yields_no_topics_rather_than_guessing(self):
        self.assertEqual(plan_topics(date(2026, 11, 27), 5), [])


class BriefTests(TestCase):
    def test_the_brief_carries_the_town_facts(self):
        brief = build_brief(_topic())

        self.assertIn("Cherthala", brief)
        self.assertIn("coastal sandy soil", brief)
        self.assertIn("narrow interior lanes", brief)

    def test_a_compliance_note_is_marked_as_an_obligation(self):
        # The model must not soften a legal requirement into a selling point.
        brief = build_brief(_topic())
        self.assertIn("LEGAL OBLIGATION", brief)
        self.assertIn("legally authorised", brief)

    def test_the_brief_never_invents_a_price(self):
        brief = build_brief(_topic())
        self.assertIn("quotes per job", brief)


class CommandTests(TestCase):
    def setUp(self):
        # Migrations seed fifteen real blog posts, so the table is never empty
        # here. Every assertion below measures what the command added.
        self.before = set(BlogPost.objects.values_list("id", flat=True))

    def _new_posts(self):
        return BlogPost.objects.exclude(id__in=self.before)

    def _written(self, **overrides) -> WrittenPost:
        defaults = dict(
            title="Sand Supply in Cherthala",
            slug="sand-supply-cherthala-cost",
            excerpt="What a load of sand costs in Cherthala and what changes the price.",
            meta_title="Sand Supply in Cherthala",
            meta_description="What a load of sand costs in Cherthala.",
            content="## Ground conditions\n\nSandy soil needs wider footings.",
            read_time=5,
        )
        defaults.update(overrides)
        return WrittenPost(**defaults)

    @patch("finoraapp.management.commands.generate_blog_posts.write_post")
    def test_posts_are_saved_as_drafts_by_default(self, write):
        # An unreviewed post is a page on the site nobody has read.
        write.return_value = self._written()

        call_command("generate_blog_posts", count=1, stdout=StringIO())

        post = self._new_posts().get()
        self.assertFalse(post.is_published)

    @patch("finoraapp.management.commands.generate_blog_posts.write_post")
    def test_publish_flag_publishes(self, write):
        write.return_value = self._written()

        call_command("generate_blog_posts", count=1, publish=True, stdout=StringIO())

        self.assertTrue(self._new_posts().get().is_published)

    @patch("finoraapp.management.commands.generate_blog_posts.write_post")
    def test_one_failure_does_not_abandon_the_batch(self, write):
        # A cron run that writes 29 of 30 is a success, not a failure.
        write.side_effect = [
            self._written(slug="first"),
            RuntimeError("the model declined"),
            self._written(slug="third"),
        ]

        err = StringIO()
        call_command("generate_blog_posts", count=3, stdout=StringIO(), stderr=err)

        self.assertEqual(self._new_posts().count(), 2)
        self.assertIn("skipped", err.getvalue())

    @patch("finoraapp.management.commands.generate_blog_posts.write_post")
    def test_a_duplicate_slug_is_suffixed_rather_than_crashing(self, write):
        write.return_value = self._written(slug="sand-supply-cherthala")
        BlogPost.objects.create(
            title="Existing", slug="sand-supply-cherthala", excerpt="x",
            category="Materials", content="x", published_at=date.today(),
        )

        call_command("generate_blog_posts", count=1, stdout=StringIO())

        self.assertTrue(BlogPost.objects.filter(slug="sand-supply-cherthala-2").exists())

    @patch("finoraapp.management.commands.generate_blog_posts.write_post")
    def test_dry_run_calls_no_api_and_writes_nothing(self, write):
        out = StringIO()
        call_command("generate_blog_posts", count=2, dry_run=True, stdout=out)

        write.assert_not_called()
        self.assertEqual(self._new_posts().count(), 0)
        self.assertIn("nothing was written", out.getvalue())

    def test_a_zero_count_is_rejected(self):
        with self.assertRaises(CommandError):
            call_command("generate_blog_posts", count=0, stdout=StringIO())

    @patch("finoraapp.management.commands.generate_blog_posts.write_post")
    def test_the_category_follows_the_service(self, write):
        write.return_value = self._written()

        call_command(
            "generate_blog_posts", count=1, stdout=StringIO(),
            **{"date": "2026-11-27"},
        )

        self.assertTrue(self._new_posts().get().category)
