"""Generates scheduled blog posts.

    python manage.py generate_blog_posts --count 30
    python manage.py generate_blog_posts --count 5 --dry-run
    python manage.py generate_blog_posts --count 30 --publish

Intended to run from cron once a day. Posts are saved as DRAFTS unless
--publish is passed, so nothing reaches the site without a person approving
it. Each post is committed as it is written, so a failure partway through
keeps the ones already done.
"""

from __future__ import annotations

from datetime import date

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.text import slugify

from finoraapp.blog_planner import plan_topics
from finoraapp.blog_writer import build_brief, write_post
from finoraapp.models import BlogPost


class Command(BaseCommand):
    help = "Writes scheduled blog posts for planned service and location topics."

    def add_arguments(self, parser):
        parser.add_argument(
            "--count", type=int, default=None,
            help="How many posts to write. Defaults to BLOG_POSTS_PER_RUN.",
        )
        parser.add_argument(
            "--publish", action="store_true",
            help="Publish immediately instead of saving as drafts. Off by default: "
                 "an unreviewed post is a page on your site nobody has read.",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Show the plan and the brief for each topic without calling the API.",
        )
        parser.add_argument(
            "--date", type=str, default="",
            help="Plan for this date (YYYY-MM-DD) instead of today.",
        )
        parser.add_argument(
            "--model", type=str, default="",
            help="Override the model id.",
        )

    def handle(self, *args, **options):
        # Falls back to the setting so cron can call the command bare and the
        # volume is changed in one place.
        count = options["count"]
        if count is None:
            count = getattr(settings, "BLOG_POSTS_PER_RUN", 5)
        if count < 1:
            raise CommandError("--count must be at least 1.")

        try:
            for_date = (
                date.fromisoformat(options["date"]) if options["date"] else date.today()
            )
        except ValueError as exc:
            raise CommandError(f"--date must be YYYY-MM-DD: {exc}") from exc

        # Topics already written, so the schedule does not repeat itself. The
        # key is stored in the slug, which is the only field guaranteed unique.
        taken = set(BlogPost.objects.values_list("slug", flat=True))

        topics = plan_topics(for_date, count, taken=taken)
        if not topics:
            raise CommandError(
                "No topics could be planned. Check that the frontend data files are "
                "readable, and that BLOG_SERVICES and BLOG_PLACES name slugs that exist."
            )

        self.stdout.write(
            f"Planned {len(topics)} topic(s) for {for_date.isoformat()}."
        )

        if options["dry_run"]:
            for topic in topics:
                self.stdout.write(self.style.MIGRATE_HEADING(f"\n{topic.key}"))
                self.stdout.write(build_brief(topic))
            self.stdout.write(self.style.SUCCESS("\nDry run: nothing was written."))
            return

        written = 0
        failed = 0

        for topic in topics:
            try:
                post = write_post(topic, model=options["model"] or None)
            except Exception as exc:
                # One bad topic must not end the batch; a cron run that writes
                # 29 of 30 posts is a success.
                failed += 1
                self.stderr.write(self.style.WARNING(f"  skipped {topic.key}: {exc}"))
                continue

            slug = self._unique_slug(post.slug or slugify(post.title))

            with transaction.atomic():
                BlogPost.objects.create(
                    title=post.title,
                    slug=slug,
                    excerpt=post.excerpt,
                    category=self._category_for(topic),
                    content=post.content,
                    meta_title=post.meta_title,
                    meta_description=post.meta_description,
                    read_time_minutes=post.read_time,
                    published_at=for_date,
                    is_published=options["publish"],
                )

            written += 1
            state = "published" if options["publish"] else "draft"
            self.stdout.write(f"  {state}: /{slug}")

        summary = f"{written} written, {failed} skipped."
        self.stdout.write(
            self.style.SUCCESS(summary) if written else self.style.ERROR(summary)
        )

        if written and not options["publish"]:
            self.stdout.write(
                "Review them under Blog posts in the admin, then tick Is published."
            )

    def _unique_slug(self, base: str) -> str:
        """Appends a counter rather than failing on a duplicate slug."""
        base = (base or "post")[:240]
        slug = base
        suffix = 2
        while BlogPost.objects.filter(slug=slug).exists():
            slug = f"{base}-{suffix}"
            suffix += 1
        return slug

    def _category_for(self, topic) -> str:
        """The blog category shown on the site."""
        if topic.service_slug == "deep-cleaning":
            return "Cleaning"
        if topic.service_slug.endswith("-supply") or "concrete" in topic.service_slug:
            return "Materials"
        if topic.service_slug in {"demolition-services", "earthmoving-excavation",
                                  "construction-transport", "equipment-rental"}:
            return "Site work"
        return "Construction"
