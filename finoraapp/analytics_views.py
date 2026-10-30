"""Public endpoint that records visitor events.

POST /api/analytics/events

Deliberately permissive about input: an analytics call must never break a page.
Anything unrecognised is dropped and the endpoint still answers 204, so a
tracking bug cannot surface as a console error on the live site.
"""

from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .analytics_geo import client_ip, is_bot, parse_device, resolve_location
from .analytics_models import AnalyticsEvent

# A second tap on the same element within this window is the same intent, not a
# second visit. Checked here as well as in the browser, because a flaky network
# can make the client retry a send it already made.
DEDUPE_WINDOW = timedelta(seconds=2)

MAX_EVENTS_PER_REQUEST = 20


def _clip(value, length: int) -> str:
    return str(value or "")[:length]


def _positive_int(value, maximum: int | None = None):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if number < 0:
        return None
    return min(number, maximum) if maximum is not None else number


class AnalyticsIngestAPIView(APIView):
    """Records a batch of events from the browser."""

    authentication_classes = []
    permission_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "analytics_ingest"

    def post(self, request, *args, **kwargs):
        user_agent = request.META.get("HTTP_USER_AGENT", "")

        # Crawlers and monitors would otherwise dominate the numbers.
        if is_bot(user_agent):
            return Response(status=status.HTTP_204_NO_CONTENT)

        payload = request.data if isinstance(request.data, dict) else {}
        events = payload.get("events")
        if not isinstance(events, list):
            events = [payload]

        location = resolve_location(client_ip(request))
        device = parse_device(user_agent)
        now = timezone.now()

        rows: list[AnalyticsEvent] = []

        for raw in events[:MAX_EVENTS_PER_REQUEST]:
            if not isinstance(raw, dict):
                continue

            kind = _clip(raw.get("kind"), 20)
            if kind not in AnalyticsEvent.Kind.values:
                continue

            visitor_id = _clip(raw.get("visitor_id"), 64)
            if not visitor_id:
                continue

            target_type = _clip(raw.get("target_type"), 20)
            if target_type and target_type not in AnalyticsEvent.Target.values:
                target_type = AnalyticsEvent.Target.OTHER

            path = _clip(raw.get("path"), 300) or "/"
            label = _clip(raw.get("label"), 200)
            href = _clip(raw.get("href"), 500)

            repeat_index = 1

            if kind == AnalyticsEvent.Kind.CLICK:
                # Identical click from the same visitor moments ago: ignore it.
                recent = AnalyticsEvent.objects.filter(
                    visitor_id=visitor_id,
                    kind=kind,
                    path=path,
                    label=label,
                    href=href,
                    created_at__gte=now - DEDUPE_WINDOW,
                ).exists()
                if recent:
                    continue

                # Genuine later clicks are kept and numbered, so the admin can
                # tell one determined customer from several interested ones.
                repeat_index = (
                    AnalyticsEvent.objects.filter(
                        visitor_id=visitor_id,
                        kind=kind,
                        path=path,
                        label=label,
                        href=href,
                    ).count()
                    + 1
                )

            rows.append(
                AnalyticsEvent(
                    kind=kind,
                    visitor_id=visitor_id,
                    session_id=_clip(raw.get("session_id"), 64),
                    path=path,
                    page_title=_clip(raw.get("page_title"), 300),
                    referrer=_clip(raw.get("referrer"), 500),
                    target_type=target_type,
                    label=label,
                    href=href,
                    section=_clip(raw.get("section"), 120),
                    repeat_index=repeat_index,
                    seconds_on_page=_positive_int(raw.get("seconds_on_page"), 86_400),
                    scroll_depth=_positive_int(raw.get("scroll_depth"), 100),
                    form_name=_clip(raw.get("form_name"), 100),
                    form_service=_clip(raw.get("form_service"), 150),
                    form_city=_clip(raw.get("form_city"), 120),
                    form_succeeded=raw.get("form_succeeded") if isinstance(raw.get("form_succeeded"), bool) else None,
                    created_at=now,
                    **location,
                    **device,
                )
            )

        if rows:
            with transaction.atomic():
                AnalyticsEvent.objects.bulk_create(rows)

        return Response(status=status.HTTP_204_NO_CONTENT)
