"""Chooses what each scheduled blog post should be about.

Topics are drawn from the same data that builds the site's service pages, so
a post about sand supply in Cherthala can state the real terrain, access and
local conditions rather than inventing them.

Scope is deliberately narrow and configurable: the point of the schedule is to
lift the services and places that matter commercially, not to cover the whole
catalogue. Rentals are excluded by default.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date

from django.conf import settings

from .analytics_performance import catalogue, load_catalogue


# Services the schedule writes about. Anything not listed is skipped, which is
# how "boost construction and cleaning, not rentals" is expressed.
DEFAULT_SERVICES = [
    # Construction and materials
    "sand-supply",
    "cement-steel-supply",
    "aggregate-quarry-supply",
    "bricks-blocks-supply",
    "roofing-materials-supply",
    "ready-mix-concrete",
    "demolition-services",
    "earthmoving-excavation",
    "construction-transport",
    "equipment-rental",
    "house-construction",
    "flat-construction",
    "commercial-construction",
    "civil-works",
    "building-renovation",
    # Cleaning
    "deep-cleaning",
]

# Places the schedule writes about, strongest commercial areas first.
DEFAULT_PLACES = [
    # Kannur district
    "kannur", "thalassery", "taliparamba", "payyannur", "mattannur",
    "kuthuparamba", "panoor", "iritty", "chakkarakkal",
    # Ernakulam / Kochi
    "ernakulam", "kochi", "kakkanad", "aluva", "perumbavoor",
    "angamaly", "tripunithura", "muvattupuzha",
]

#: Angles that make two posts about the same service read differently. The
#: angle is part of the topic key, so the same service and town can recur
#: later in the year without repeating the article.
ANGLES = [
    ("cost", "what it costs and what changes the price"),
    ("choosing", "how to choose the right grade, spec or option"),
    ("mistakes", "the mistakes that cost people money"),
    ("timing", "when to do it and how long it takes"),
    ("local", "what the ground and access in this town mean for the job"),
    ("checklist", "what to check before you commit"),
    ("permits", "the approvals and paperwork involved"),
    ("comparison", "how the common options compare"),
]


@dataclass
class Topic:
    """One planned post."""

    service_slug: str
    service_name: str
    place_slug: str
    place_name: str
    angle: str
    angle_label: str

    #: Facts pulled from the site data, handed to the writer so the post can
    #: be specific rather than generic.
    facts: dict = field(default_factory=dict)

    @property
    def key(self) -> str:
        """Stable identity, so the same topic is not written twice."""
        return f"{self.service_slug}|{self.place_slug}|{self.angle}"

    @property
    def slug_hint(self) -> str:
        return f"{self.service_slug}-{self.place_slug}-{self.angle}"


def _setting(name: str, default):
    """Reads a setting, falling back when it is absent OR explicitly None.

    The settings module sets BLOG_SERVICES to None when the env var is empty,
    which getattr happily returns — so a plain getattr default is not enough.
    """
    value = getattr(settings, name, None)
    return default if value is None else value


def _town_facts() -> dict[str, dict]:
    """Terrain, access and local notes per town, from construction-towns.mjs.

    Returns an empty mapping when the frontend is not on disk; posts then
    carry the service facts only, which is thinner but still accurate.
    """
    import re

    from .analytics_performance import _frontend_dir

    root = _frontend_dir()
    if root is None:
        return {}

    path = root / "scripts" / "construction-towns.mjs"
    if not path.is_file():
        return {}

    text = path.read_text(encoding="utf-8")
    facts: dict[str, dict] = {}

    # Each entry is  "Town Name": { district: "...", terrain: "...", ... }
    for match in re.finditer(r'^\s{2}"([A-Z][A-Za-z .]+)":\s*\{(.*?)\n\s{2}\},', text, re.S | re.M):
        name, body = match.group(1), match.group(2)
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        entry = {}
        for field_name in ("district", "terrain", "access", "building", "note"):
            found = re.search(rf'{field_name}:\s*\n?\s*"([^"]+)"', body)
            if found:
                entry[field_name] = found.group(1)
        if entry:
            facts[slug] = entry

    return facts


def _service_facts() -> dict[str, dict]:
    """Intro, item list and any compliance note per service."""
    import re

    from .analytics_performance import _block, _frontend_dir

    root = _frontend_dir()
    if root is None:
        return {}

    facts: dict[str, dict] = {}
    scripts = root / "scripts"

    for file_name, export_name in (
        ("construction-data.mjs", "constructionCategories"),
        ("design-data.mjs", "designCategories"),
        ("site-data.mjs", "services"),
    ):
        path = scripts / file_name
        if not path.is_file():
            continue

        block = _block(path.read_text(encoding="utf-8"), export_name)

        # Split on each object's slug so fields are not read across entries.
        for chunk in re.split(r'\n\s{2}\{', block):
            slug_match = re.search(r'slug:\s*"([a-z0-9-]+)"', chunk)
            if not slug_match:
                continue
            entry = {}
            intro = re.search(r'intro:\s*\n?\s*"([^"]+)"', chunk)
            if intro:
                entry["intro"] = intro.group(1)
            compliance = re.search(r'compliance:\s*\n?\s*"([^"]+)"', chunk)
            if compliance:
                entry["compliance"] = compliance.group(1)
            items = re.search(r'items:\s*\[(.*?)\]', chunk, re.S)
            if items:
                entry["items"] = re.findall(r'"([^"]+)"', items.group(1))[:10]
            if entry:
                facts[slug_match.group(1)] = entry

    return facts


def plan_topics(for_date: date, count: int, *, taken: set[str] | None = None) -> list[Topic]:
    """Picks `count` topics for a given day, avoiding anything already written.

    Selection is deterministic for a date, so re-running the command on the
    same day produces the same plan rather than a fresh random set. Service
    and place rotate at different rates so consecutive days do not all cover
    the same service.
    """
    taken = taken or set()

    if not catalogue().services:
        load_catalogue()

    names = catalogue()
    services = [s for s in _setting("BLOG_SERVICES", DEFAULT_SERVICES) if s in names.services]
    places = [p for p in _setting("BLOG_PLACES", DEFAULT_PLACES) if p in names.places]

    if not services or not places:
        return []

    town_facts = _town_facts()
    service_facts = _service_facts()

    # A day-dependent offset, so the plan moves through the matrix over time
    # instead of restarting at the same pair every morning.
    seed = int(hashlib.sha256(for_date.isoformat().encode()).hexdigest()[:8], 16)

    topics: list[Topic] = []
    attempts = 0
    index = seed

    # Walk the service x place x angle space until enough unused topics are
    # found. Bounded so a nearly exhausted matrix cannot spin forever.
    while len(topics) < count and attempts < count * 50:
        attempts += 1
        index += 1

        # Co-prime strides so a single day's batch spreads across services,
        # towns and angles instead of marching through one axis. Stepping all
        # three by the same index produced 30 posts about one town.
        service = services[index % len(services)]
        place = places[(index * 7) % len(places)]
        angle, angle_label = ANGLES[(index * 3) % len(ANGLES)]

        topic = Topic(
            service_slug=service,
            service_name=names.services[service],
            place_slug=place,
            place_name=names.places[place],
            angle=angle,
            angle_label=angle_label,
            facts={
                "town": town_facts.get(place, {}),
                "service": service_facts.get(service, {}),
            },
        )

        if topic.key in taken:
            continue
        if any(t.key == topic.key for t in topics):
            continue

        topics.append(topic)

    return topics
