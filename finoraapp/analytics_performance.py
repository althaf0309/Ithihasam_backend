"""Groups page analytics by service and location, and finds pages that do not convert.

The dashboard already reported top pages, but a raw URL list cannot answer the
question that matters with 2,759 pages: which *service* earns enquiries, where,
and which pages pull visitors and return nothing.

A path like /sand-supply-cherthala carries both halves joined by a hyphen, and
both halves themselves contain hyphens, so it cannot be split naively. The
catalogue of known service and place slugs is read from the frontend data files
and matched by longest suffix, the same way the React router resolves them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from django.conf import settings
from django.db.models import Count, Q

from .analytics_models import AnalyticsEvent


# --------------------------------------------------------------------------
# Slug catalogue
# --------------------------------------------------------------------------

@dataclass
class Catalogue:
    """Known service and place slugs."""

    services: dict[str, str] = field(default_factory=dict)
    places: dict[str, str] = field(default_factory=dict)

    @property
    def place_slugs(self) -> list[str]:
        """Longest first, so suffix matching cannot pick a shorter tail."""
        return sorted(self.places, key=len, reverse=True)


_SLUG_NAME = re.compile(
    r'slug:\s*"([a-z0-9-]+)",\s*\n\s*(?:(?://[^\n]*|/\*.*?\*/)\s*\n\s*)*name:\s*"([^"]+)"',
    re.S,
)


def _block(text: str, export_name: str) -> str:
    """The body of one `export const <name> = [ ... ]` declaration.

    Scoping matters: construction-data.mjs declares districts and categories in
    the same file with the same shape, so an unscoped scan reported Kannur as a
    service. Bracket counting is enough for these flat array literals.
    """
    start = text.find(f"export const {export_name}")
    if start == -1:
        return ""

    open_at = text.find("[", start)
    if open_at == -1:
        return ""

    depth = 0
    for i in range(open_at, len(text)):
        if text[i] == "[":
            depth += 1
        elif text[i] == "]":
            depth -= 1
            if depth == 0:
                return text[open_at : i + 1]
    return ""


def _titles_from_js(text: str, export_name: str) -> dict[str, str]:
    """Pulls slug/name pairs out of one exported array.

    Deliberately a regex rather than a parser: these files are plain object
    literals, and adding a Node dependency inside Django would be worse than a
    pattern that fails safely to an empty dict.
    """
    found: dict[str, str] = {}
    for slug, name in _SLUG_NAME.findall(_block(text, export_name)):
        found.setdefault(slug, name)
    return found


def _frontend_dir() -> Path | None:
    """Locates the frontend checkout, which holds the slug data files."""
    configured = getattr(settings, "FRONTEND_DIR", None)
    if configured and Path(configured).is_dir():
        return Path(configured)

    for candidate in (
        Path(settings.BASE_DIR).parent / "Ithihasam_frontend",
        Path(settings.BASE_DIR).parent / "pro-home-pros",
    ):
        if candidate.is_dir():
            return candidate
    return None


def load_catalogue() -> Catalogue:
    """Reads service and place slugs from the frontend data files.

    Returns an empty catalogue when the frontend is not on disk, which is the
    case in tests and on a backend-only deploy. Callers then report raw paths
    rather than failing.
    """
    catalogue = Catalogue()
    root = _frontend_dir()
    if root is None:
        return catalogue

    scripts = root / "scripts"

    # Services, each from its own export so districts are not mistaken for one.
    for file_name, export_name in (
        ("construction-data.mjs", "constructionCategories"),
        ("design-data.mjs", "designCategories"),
        ("site-data.mjs", "services"),
    ):
        path = scripts / file_name
        if path.is_file():
            catalogue.services.update(_titles_from_js(path.read_text(encoding="utf-8"), export_name))

    # Districts and service areas.
    for file_name, export_name in (
        ("construction-data.mjs", "constructionDistricts"),
        ("site-data.mjs", "serviceAreas"),
    ):
        path = scripts / file_name
        if path.is_file():
            catalogue.places.update(_titles_from_js(path.read_text(encoding="utf-8"), export_name))

    # Towns, which construction-towns.mjs keys by display name rather than slug.
    towns = scripts / "construction-towns.mjs"
    if towns.is_file():
        for town in re.findall(
            r'^\s{2}"([A-Z][A-Za-z .]+)":\s*\{', towns.read_text(encoding="utf-8"), re.M
        ):
            slug = re.sub(r"[^a-z0-9]+", "-", town.lower()).strip("-")
            catalogue.places.setdefault(slug, town)

    return catalogue


_CATALOGUE: Catalogue | None = None


def catalogue() -> Catalogue:
    """Cached catalogue. Call reset_catalogue() after the frontend is rebuilt."""
    global _CATALOGUE
    if _CATALOGUE is None:
        _CATALOGUE = load_catalogue()
    return _CATALOGUE


def reset_catalogue() -> None:
    global _CATALOGUE
    _CATALOGUE = None


# --------------------------------------------------------------------------
# Path parsing
# --------------------------------------------------------------------------

def split_path(path: str) -> tuple[str | None, str | None]:
    """Returns (service label, place label) for a page path.

    Handles the shapes the site produces:

        /construction/sand-supply     -> service only
        /sand-supply-cherthala        -> service + place
        /services/roofing-fabrication -> service only
        /rentals/trivandrum           -> rental + place
        /locations/thalassery         -> place only

    Matching is by longest place suffix first, because both halves of the slug
    contain hyphens and a shorter place name can be the tail of a longer one.
    """
    if not path or path == "/":
        return None, None

    slug = path.strip("/")
    cat = catalogue()

    if slug.startswith("locations/"):
        rest = slug[len("locations/"):]
        return None, cat.places.get(rest, rest.replace("-", " ").title())

    if slug.startswith("rentals"):
        parts = slug.split("/")
        place = parts[1] if len(parts) > 1 else ""
        if place in ("for",):
            return "Furniture Rental", None
        return (
            "Furniture Rental",
            cat.places.get(place, place.replace("-", " ").title()) if place else None,
        )

    for prefix in ("construction/", "services/"):
        if slug.startswith(prefix):
            rest = slug[len(prefix):]
            return cat.services.get(rest, rest.replace("-", " ").title()), None

    if "/" in slug:
        return None, None  # blog, news and other sections

    for place_slug in cat.place_slugs:
        if slug.endswith("-" + place_slug):
            service_slug = slug[: -(len(place_slug) + 1)]
            service = cat.services.get(service_slug)
            if service:
                return service, cat.places[place_slug]
            # An unknown service half still tells us the place, and the local
            # template pages (ac-repair, tv-repair) land here.
            return service_slug.replace("-", " ").title(), cat.places[place_slug]

    return cat.services.get(slug), None


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------

CONTACT_TARGETS = [
    AnalyticsEvent.Target.PHONE,
    AnalyticsEvent.Target.WHATSAPP,
    AnalyticsEvent.Target.EMAIL,
]


def _rate(enquiries: int, visitors: int) -> float:
    return round(enquiries / visitors * 100, 1) if visitors else 0.0


def performance_by_path(since) -> list[dict]:
    """Per-path visitors and enquiries within the window.

    An enquiry is any attempt at contact — form, call or WhatsApp — because
    most customers here call rather than fill a form, and counting forms alone
    would show working pages as dead.
    """
    rows = (
        AnalyticsEvent.objects.filter(created_at__gte=since)
        .exclude(path="")
        .values("path")
        .annotate(
            visitors=Count("visitor_id", distinct=True, filter=Q(kind=AnalyticsEvent.Kind.PAGE_VIEW)),
            views=Count("id", filter=Q(kind=AnalyticsEvent.Kind.PAGE_VIEW)),
            forms=Count("id", filter=Q(kind=AnalyticsEvent.Kind.FORM_SUBMIT)),
            contacts=Count(
                "id",
                filter=Q(kind=AnalyticsEvent.Kind.CLICK, target_type__in=CONTACT_TARGETS),
            ),
        )
        .order_by("-views")
    )

    out = []
    for row in rows:
        enquiries = row["forms"] + row["contacts"]
        service, place = split_path(row["path"])
        out.append(
            {
                **row,
                "service": service,
                "place": place,
                "enquiries": enquiries,
                "rate": _rate(enquiries, row["visitors"]),
            }
        )
    return out


def _aggregate(rows: list[dict], key: str) -> list[dict]:
    totals: dict[str, dict] = {}

    for row in rows:
        label = row.get(key)
        if not label:
            continue
        bucket = totals.setdefault(
            label, {"label": label, "views": 0, "visitors": 0, "enquiries": 0, "pages": 0}
        )
        bucket["views"] += row["views"]
        bucket["visitors"] += row["visitors"]
        bucket["enquiries"] += row["enquiries"]
        bucket["pages"] += 1

    for bucket in totals.values():
        bucket["rate"] = _rate(bucket["enquiries"], bucket["visitors"])

    return sorted(totals.values(), key=lambda b: b["views"], reverse=True)


def performance_report(since, *, min_views: int = 5) -> dict:
    """Everything the dashboard panel needs.

    `min_views` keeps a page that one person saw once out of the dead list; at
    that volume zero enquiries means nothing.
    """
    rows = performance_by_path(since)

    by_service = _aggregate(rows, "service")
    by_place = _aggregate(rows, "place")

    converting = [r for r in rows if r["enquiries"]]
    dead = [r for r in rows if r["views"] >= min_views and not r["enquiries"]]

    return {
        # False means the frontend data files were not found, so the service
        # and location columns will be empty and only raw paths are reliable.
        "catalogue_loaded": bool(catalogue().services),
        "by_service": by_service[:25],
        "by_place": by_place[:25],
        # Best first: the pages actually earning enquiries.
        "best_pages": sorted(converting, key=lambda r: (-r["enquiries"], -r["rate"]))[:20],
        # The list worth acting on: real traffic, nothing to show for it.
        "dead_pages": sorted(dead, key=lambda r: -r["views"])[:25],
        "dead_count": len(dead),
        "min_views": min_views,
        "services_without_enquiries": [s for s in by_service if not s["enquiries"]],
    }


# --------------------------------------------------------------------------
# Where to expand next
# --------------------------------------------------------------------------

def _norm(value: str) -> str:
    """Loose key for comparing a typed or GeoIP place name against a slug."""
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower())


def covered_places() -> set[str]:
    """Normalised names of every town and district that already has pages."""
    return {_norm(name) for name in catalogue().places.values()}


def expansion_report(since, *, min_signal: int = 3) -> dict:
    """Where demand exists that the site does not yet serve.

    Three signals, strongest first:

    1. `form_city` — the customer typed where they need the work. Unambiguous
       intent, and it is the only one that survives a VPN or a mobile network
       routing through another city.
    2. Visitor city with enquiries — people in a place who went on to call or
       message, reading pages written about somewhere else.
    3. Visitor city by volume — traffic from a place with no page of its own.

    A place already in the catalogue is not a gap, however much traffic it
    has: that is the existing pages working, which the performance panels
    already report.
    """
    covered = covered_places()
    events = AnalyticsEvent.objects.filter(created_at__gte=since)

    # --- 1. Cities people typed into the booking form ---------------------
    typed: dict[str, dict] = {}
    rows = (
        events.filter(kind=AnalyticsEvent.Kind.FORM_SUBMIT)
        .exclude(form_city="")
        .values("form_city", "form_service")
    )
    for row in rows:
        key = _norm(row["form_city"])
        if not key:
            continue
        bucket = typed.setdefault(
            key,
            {"place": row["form_city"].strip().title(), "requests": 0,
             "services": set(), "covered": key in covered},
        )
        bucket["requests"] += 1
        if row["form_service"]:
            bucket["services"].add(row["form_service"])

    for bucket in typed.values():
        bucket["services"] = ", ".join(sorted(bucket["services"])[:4])

    # --- 2 & 3. Where visitors actually are -------------------------------
    by_city = (
        events.exclude(city="")
        .values("city", "region")
        .annotate(
            visitors=Count("visitor_id", distinct=True),
            views=Count("id", filter=Q(kind=AnalyticsEvent.Kind.PAGE_VIEW)),
            enquiries=Count(
                "id",
                filter=Q(kind=AnalyticsEvent.Kind.FORM_SUBMIT)
                | Q(kind=AnalyticsEvent.Kind.CLICK, target_type__in=CONTACT_TARGETS),
            ),
        )
        .order_by("-visitors")
    )

    visitor_gaps, visitor_covered = [], []
    for row in by_city:
        entry = {
            **row,
            "rate": _rate(row["enquiries"], row["visitors"]),
            "covered": _norm(row["city"]) in covered,
        }
        (visitor_covered if entry["covered"] else visitor_gaps).append(entry)

    # Which services those uncovered visitors were reading, so a new page can
    # be written about the right thing rather than guessed at.
    gap_names = {row["city"] for row in visitor_gaps[:10]}
    wanted: dict[str, dict] = {}
    if gap_names:
        for row in (
            events.filter(city__in=gap_names, kind=AnalyticsEvent.Kind.PAGE_VIEW)
            .exclude(path="")
            .values("city", "path")
            .annotate(views=Count("id"))
            .order_by("-views")[:200]
        ):
            service, _ = split_path(row["path"])
            if not service:
                continue
            key = f"{row['city']}|{service}"
            bucket = wanted.setdefault(
                key, {"city": row["city"], "service": service, "views": 0}
            )
            bucket["views"] += row["views"]

    return {
        "catalogue_loaded": bool(catalogue().places),
        "min_signal": min_signal,
        # Strongest signal: typed by a real customer, no page for it yet.
        "requested_uncovered": sorted(
            (b for b in typed.values() if not b["covered"]),
            key=lambda b: -b["requests"],
        )[:20],
        "requested_covered": sorted(
            (b for b in typed.values() if b["covered"]),
            key=lambda b: -b["requests"],
        )[:10],
        # Visitors in places with no page, ranked by enquiries then volume.
        "visitor_gaps": sorted(
            (r for r in visitor_gaps if r["visitors"] >= min_signal),
            key=lambda r: (-r["enquiries"], -r["visitors"]),
        )[:20],
        # The places already working, for comparison.
        "visitor_covered": visitor_covered[:10],
        "wanted_services": sorted(wanted.values(), key=lambda b: -b["views"])[:20],
    }
