"""Analytics dashboard inside the Django admin.

Gives the office a single screen answering: who contacted us, from where, and
what they clicked. Calls and WhatsApp taps matter most — for a home-services
business those are the lead, not the form.
"""

from __future__ import annotations

import csv
from datetime import timedelta

from django.contrib import admin, messages
from django.db.models import Count, Q
from django.http import HttpResponse
from django.template.response import TemplateResponse
from django.urls import path
from django.utils import timezone
from django.utils.html import format_html

from .analytics_models import AnalyticsEvent

# Windows offered by the dashboard's period selector.
PERIODS = {"1": 1, "7": 7, "30": 30, "90": 90}


def _csv_safe(value) -> str:
    """Neutralise spreadsheet formula injection.

    A label like "=HYPERLINK(...)" would execute when the export is opened in
    Excel. Prefixing with an apostrophe keeps it inert and still readable.
    """
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


@admin.register(AnalyticsEvent)
class AnalyticsEventAdmin(admin.ModelAdmin):
    list_display = ("created_at_ist", "who", "kind", "what", "where", "device_type", "repeat_index")
    list_filter = ("kind", "target_type", "device_type", "country", "created_at")
    search_fields = ("label", "href", "path", "city", "form_service", "person_name", "person_phone")
    date_hierarchy = "created_at"
    list_per_page = 100

    # Events are a record of what happened; editing one would be falsifying it.
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    @admin.display(description="Time (IST)", ordering="created_at")
    def created_at_ist(self, obj):
        return timezone.localtime(obj.created_at).strftime("%d %b %Y, %H:%M")

    @admin.display(description="Who", ordering="person_name")
    def who(self, obj):
        """The person, once known.

        A visitor is anonymous until they submit the form; the server then
        back-fills the name across that visit, so earlier clicks become
        attributable to someone you can actually call.
        """
        if obj.person_name:
            return format_html("<strong>{}</strong>", obj.person_name)
        return format_html('<span style="opacity:.5">anonymous</span>')

    @admin.action(description="Erase this visitor's data (DPDP request)")
    def erase_visitor(self, request, queryset):
        """Deletes every event for the selected visitors.

        The DPDP Act gives a person the right to erasure. Deleting by visitor
        rather than by row removes their whole history, not just what happened
        to be on screen.
        """
        visitor_ids = list(queryset.values_list("visitor_id", flat=True).distinct())
        deleted, _ = AnalyticsEvent.objects.filter(visitor_id__in=visitor_ids).delete()
        self.message_user(
            request,
            f"Erased {deleted} event(s) for {len(visitor_ids)} visitor(s).",
            messages.SUCCESS,
        )

    @admin.action(description="Purge events past the retention window")
    def purge_old(self, request, queryset):
        from .analytics_models import purge_expired_events

        deleted = purge_expired_events()
        self.message_user(request, f"Purged {deleted} expired event(s).", messages.SUCCESS)

    actions = ["erase_visitor", "purge_old"]

    @admin.display(description="What")
    def what(self, obj):
        if obj.kind == AnalyticsEvent.Kind.CLICK:
            icon = {
                "whatsapp": "💬", "phone": "📞", "email": "✉️",
                "maps": "📍", "form": "📝",
            }.get(obj.target_type, "🔗")
            return format_html("{} {}", icon, obj.label or obj.href or "—")
        if obj.kind == AnalyticsEvent.Kind.FORM_SUBMIT:
            return format_html("📝 {}", obj.form_service or obj.form_name or "Booking")
        return obj.path

    @admin.display(description="Where")
    def where(self, obj):
        return obj.location

    def get_urls(self):
        return [
            path("dashboard/", self.admin_site.admin_view(self.dashboard_view), name="analytics-dashboard"),
            path("dashboard/export/", self.admin_site.admin_view(self.export_view), name="analytics-export"),
            *super().get_urls(),
        ]

    # ------------------------------------------------------------- dashboard

    def _window(self, request):
        days = PERIODS.get(request.GET.get("days", "7"), 7)
        return days, timezone.now() - timedelta(days=days)

    def dashboard_view(self, request):
        days, since = self._window(request)
        events = AnalyticsEvent.objects.filter(created_at__gte=since)
        clicks = events.filter(kind=AnalyticsEvent.Kind.CLICK)

        def people(queryset):
            return queryset.values("visitor_id").distinct().count()

        contact_clicks = clicks.filter(
            target_type__in=[
                AnalyticsEvent.Target.PHONE,
                AnalyticsEvent.Target.WHATSAPP,
                AnalyticsEvent.Target.EMAIL,
            ]
        )

        summary = {
            "visitors": people(events),
            "page_views": events.filter(kind=AnalyticsEvent.Kind.PAGE_VIEW).count(),
            "calls": clicks.filter(target_type=AnalyticsEvent.Target.PHONE).count(),
            "whatsapp": clicks.filter(target_type=AnalyticsEvent.Target.WHATSAPP).count(),
            "forms": events.filter(kind=AnalyticsEvent.Kind.FORM_SUBMIT).count(),
            # The number that matters: share of visitors who tried to make
            # contact at all, by any route.
            "contact_rate": round(people(contact_clicks) / people(events) * 100, 1) if people(events) else 0.0,
        }

        by_target = list(
            clicks.values("target_type")
            .annotate(
                total=Count("id"),
                people=Count("visitor_id", distinct=True),
                repeats=Count("id", filter=Q(repeat_index__gt=1)),
            )
            .order_by("-total")
        )
        labels = dict(AnalyticsEvent.Target.choices)
        for row in by_target:
            row["name"] = labels.get(row["target_type"], row["target_type"] or "Other")

        context = {
            **self.admin_site.each_context(request),
            "title": "Visitor analytics",
            "days": days,
            "periods": sorted(PERIODS.items(), key=lambda item: int(item[0])),
            "summary": summary,
            "by_target": by_target,
            "top_locations": list(
                events.exclude(city="")
                .values("city", "region", "country")
                .annotate(total=Count("id"), people=Count("visitor_id", distinct=True))
                .order_by("-people")[:15]
            ),
            "top_clicked": list(
                clicks.values("label", "target_type", "path")
                .annotate(total=Count("id"), people=Count("visitor_id", distinct=True))
                .order_by("-total")[:20]
            ),
            "top_pages": list(
                events.filter(kind=AnalyticsEvent.Kind.PAGE_VIEW)
                .values("path")
                .annotate(total=Count("id"), people=Count("visitor_id", distinct=True))
                .order_by("-total")[:20]
            ),
            "devices": list(
                events.exclude(device_type="")
                .values("device_type")
                .annotate(total=Count("id"), people=Count("visitor_id", distinct=True))
                .order_by("-total")
            ),
            "form_submissions": list(
                events.filter(kind=AnalyticsEvent.Kind.FORM_SUBMIT)
                .values("created_at", "form_service", "form_city", "city", "country", "path", "form_succeeded")
                .order_by("-created_at")[:50]
            ),
            # Visitors who gave a name, with what they did. This is the panel
            # that turns analytics into a callback list.
            "identified": list(
                events.exclude(person_name="")
                .values("person_name", "person_phone", "city", "country", "visitor_id")
                .annotate(
                    events_count=Count("id"),
                    calls=Count("id", filter=Q(target_type=AnalyticsEvent.Target.PHONE)),
                    whatsapp=Count("id", filter=Q(target_type=AnalyticsEvent.Target.WHATSAPP)),
                    forms=Count("id", filter=Q(kind=AnalyticsEvent.Kind.FORM_SUBMIT)),
                )
                .order_by("-events_count")[:50]
            ),
            "recent_clicks": list(
                clicks.values(
                    "created_at", "target_type", "label", "href", "path",
                    "city", "region", "country", "device_type", "repeat_index",
                    "person_name", "person_phone",
                ).order_by("-created_at")[:200]
            ),
            "target_labels": labels,
        }
        return TemplateResponse(request, "admin/analytics_dashboard.html", context)

    def export_view(self, request):
        days, since = self._window(request)
        rows = (
            AnalyticsEvent.objects.filter(created_at__gte=since)
            .order_by("-created_at")
            .values_list(
                "created_at", "kind", "target_type", "label", "href", "path",
                "city", "region", "country", "device_type", "browser",
                "repeat_index", "form_service", "form_city",
                "person_name", "person_phone",
            )
        )

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="ithihasam-analytics-{days}d.csv"'

        writer = csv.writer(response)
        writer.writerow([
            "Time (IST)", "Kind", "Target", "Label", "Href", "Path",
            "City", "Region", "Country", "Device", "Browser",
            "Repeat #", "Service", "Form city", "Name", "Phone",
        ])
        for row in rows.iterator(chunk_size=500):
            created, *rest = row
            writer.writerow(
                [timezone.localtime(created).strftime("%Y-%m-%d %H:%M:%S")]
                + [_csv_safe(value) for value in rest]
            )

        return response
