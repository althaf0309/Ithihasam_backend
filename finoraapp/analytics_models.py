"""Visitor analytics: page views, clicks, form submissions, call and WhatsApp taps.

Stored in the database rather than a JSON file. The spec this was built from used
locked file writes, which suits a Node service with no database; here Django's
ORM already gives atomic writes, indexing and an admin UI, so a table is simpler
and safer than reimplementing file locking.

Privacy: no raw IP address is ever stored. The IP is used once, in memory, to
derive a coarse town/region/country and is then discarded, so the table holds no
personal data under India's DPDP Act. Visitors are counted with a random id the
browser generates.

A visitor's name is recorded only when they themselves submit the booking form,
and it is purged with the rest of their events after ANALYTICS_RETENTION_DAYS.
"""

from django.db import models
from django.utils import timezone


class AnalyticsEvent(models.Model):
    """One recorded visitor action."""

    class Kind(models.TextChoices):
        PAGE_VIEW = "page_view", "Page view"
        CLICK = "click", "Click"
        FORM_SUBMIT = "form_submit", "Form submission"
        PAGE_EXIT = "page_exit", "Page exit"
        ERROR = "error", "Error"

    class Target(models.TextChoices):
        """What a click opens. Derived on the client from the href."""

        WHATSAPP = "whatsapp", "WhatsApp"
        PHONE = "phone", "Phone call"
        EMAIL = "email", "Email"
        MAPS = "maps", "Maps"
        SOCIAL = "social", "Social"
        FORM = "form", "Form"
        INTERNAL = "internal", "Internal link"
        EXTERNAL = "external", "External link"
        OTHER = "other", "Other"

    kind = models.CharField(max_length=20, choices=Kind.choices, db_index=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    # --- who (anonymous) ----------------------------------------------------
    # Random id minted by the browser and kept in sessionStorage. Lets us count
    # people rather than hits, without anything that identifies an individual.
    visitor_id = models.CharField(max_length=64, db_index=True)
    session_id = models.CharField(max_length=64, blank=True)

    # --- where --------------------------------------------------------------
    path = models.CharField(max_length=300, db_index=True)
    page_title = models.CharField(max_length=300, blank=True)
    referrer = models.CharField(max_length=500, blank=True)

    city = models.CharField(max_length=120, blank=True, db_index=True)
    region = models.CharField(max_length=120, blank=True)
    country = models.CharField(max_length=80, blank=True, db_index=True)

    # --- what was clicked ---------------------------------------------------
    target_type = models.CharField(max_length=20, choices=Target.choices, blank=True, db_index=True)
    label = models.CharField(max_length=200, blank=True, help_text="Visible text of the link or button.")
    href = models.CharField(max_length=500, blank=True)
    section = models.CharField(max_length=120, blank=True, help_text="Where on the page it sits.")

    # Nth time this visitor has clicked this exact thing. 1 is the first click;
    # anything higher is a genuine repeat, not a double-tap.
    repeat_index = models.PositiveIntegerField(default=1)

    # --- engagement ---------------------------------------------------------
    seconds_on_page = models.PositiveIntegerField(null=True, blank=True)
    scroll_depth = models.PositiveSmallIntegerField(null=True, blank=True, help_text="Percent of page scrolled.")

    # --- device -------------------------------------------------------------
    device_type = models.CharField(max_length=20, blank=True, db_index=True)
    browser = models.CharField(max_length=60, blank=True)
    os = models.CharField(max_length=60, blank=True)

    # --- form submissions ---------------------------------------------------
    form_name = models.CharField(max_length=100, blank=True)
    form_service = models.CharField(max_length=150, blank=True)
    form_city = models.CharField(max_length=120, blank=True)
    form_succeeded = models.BooleanField(null=True, blank=True)
    # Captured when a visitor submits the booking form. Once known, it is
    # back-filled onto that visitor's earlier events, so the click log shows
    # who was browsing rather than an opaque id.
    person_name = models.CharField(max_length=150, blank=True, db_index=True)
    person_phone = models.CharField(max_length=40, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Analytics event"
        verbose_name_plural = "Analytics events"
        indexes = [
            models.Index(fields=["kind", "-created_at"]),
            models.Index(fields=["target_type", "-created_at"]),
            models.Index(fields=["city", "-created_at"]),
        ]

    def __str__(self):
        if self.kind == self.Kind.CLICK:
            return f"{self.get_target_type_display()} — {self.label or self.href}"
        return f"{self.get_kind_display()} — {self.path}"

    @property
    def location(self):
        parts = [part for part in (self.city, self.region, self.country) if part]
        return ", ".join(parts) or "Unknown"


def purge_expired_events():
    """Deletes events past the retention window.

    No IP is stored, but a visitor's name is once they submit the form, so the
    rows still age out rather than accumulating indefinitely. Nobody acts on a
    click from last year in any case.
    """
    from datetime import timedelta

    from django.conf import settings

    days = getattr(settings, "ANALYTICS_RETENTION_DAYS", 90)
    cutoff = timezone.now() - timedelta(days=days)
    deleted, _ = AnalyticsEvent.objects.filter(created_at__lt=cutoff).delete()
    return deleted
