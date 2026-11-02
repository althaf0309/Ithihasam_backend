"""Deriving a coarse location, device and bot verdict from a request.

The spec this follows hit two problems worth carrying over as comments:

  * Location always "Unknown" — the previous implementation read Cloudflare
    headers (CF-IPCountry and friends), but ithihasam.in is served straight from
    nginx on EC2, so those headers never exist. The client IP comes from
    X-Forwarded-For instead, set by nginx.

  * Headless browsers were filtered as bots, so nothing was recorded during
    browser tests. is_bot() therefore ignores "headless" unless another bot
    marker is present.

No raw IP is stored anywhere. It is resolved in memory and discarded.
"""

from __future__ import annotations

import ipaddress
import logging
import os
import re

# Substrings that reliably mark automated traffic. Deliberately excludes
# "headless", which would also exclude the project's own browser tests.
logger = logging.getLogger("finoraapp")


BOT_MARKERS = (
    "bot", "crawler", "spider", "slurp", "scrapy", "curl", "wget",
    "python-requests", "httpclient", "go-http-client", "okhttp",
    "lighthouse", "pagespeed", "gtmetrix", "pingdom", "uptimerobot",
    "semrush", "ahrefs", "mj12", "dotbot", "petalbot", "bytespider",
    "gptbot", "claudebot", "perplexitybot", "ccbot", "applebot",
)

PRIVATE_PREFIXES = ("10.", "192.168.", "127.", "172.16.", "172.17.", "172.18.",
                    "172.19.", "172.2", "172.30.", "172.31.", "169.254.")


def is_bot(user_agent: str) -> bool:
    """True when the user agent looks automated."""
    if not user_agent:
        # Real browsers always send one; its absence is a stronger signal than
        # any single keyword.
        return True

    agent = user_agent.lower()
    return any(marker in agent for marker in BOT_MARKERS)


def client_ip(request) -> str | None:
    """The visitor's IP, read from the proxy header nginx sets.

    Cloudflare headers are not consulted: this site is not behind Cloudflare,
    and trusting a header that is never set is how the previous version ended
    up recording every location as Unknown.
    """
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        # Left-most entry is the original client; the rest are proxies.
        candidate = forwarded.split(",")[0].strip()
    else:
        candidate = request.META.get("REMOTE_ADDR", "").strip()

    if not candidate:
        return None

    try:
        ipaddress.ip_address(candidate)
    except ValueError:
        return None

    return candidate


def is_private(ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip).is_private
    except ValueError:
        return True


def resolve_location(ip: str | None) -> dict[str, str]:
    """Map an IP to a coarse town/region/country.

    Uses a local GeoIP2/DB-IP City Lite database when one is configured, so no
    visitor IP is ever sent to a third party. Without a database the fields stay
    blank rather than guessing, and the admin shows "Unknown".

    To enable:
        pip install geoip2
        download DB-IP City Lite (.mmdb), set GEOIP_CITY_DB in .env
    """
    blank = {"city": "", "region": "", "country": ""}

    if not ip or is_private(ip):
        return blank

    reader = _get_reader()
    if reader is None:
        return blank

    try:
        response = reader.city(ip)
    except Exception:
        # A lookup miss is normal for many IP ranges; never let it break the
        # request that is trying to record an event.
        return blank

    return {
        "city": (response.city.name or "")[:120],
        "region": (response.subdivisions.most_specific.name or "")[:120] if response.subdivisions else "",
        "country": (response.country.name or "")[:80],
    }


_reader = None
_reader_loaded = False


def _get_reader():
    """Open the GeoIP database once, lazily, and reuse it."""
    global _reader, _reader_loaded

    if _reader_loaded:
        return _reader

    _reader_loaded = True

    from django.conf import settings

    db_path = getattr(settings, "GEOIP_CITY_DB", "")
    if not db_path:
        # Silence here is why every event read "Unknown" with no clue as to why.
        logger.warning(
            "GEOIP_CITY_DB is not set, so analytics cannot resolve locations. "
            "Download a City database (DB-IP City Lite or GeoLite2) and point "
            "GEOIP_CITY_DB at the .mmdb file."
        )
        return None

    if not os.path.exists(db_path):
        logger.error("GEOIP_CITY_DB points at %s, which does not exist.", db_path)
        return None

    try:
        import geoip2.database

        _reader = geoip2.database.Reader(db_path)
        logger.info("GeoIP database loaded from %s.", db_path)
    except Exception:
        logger.exception("Could not open the GeoIP database at %s.", db_path)
        _reader = None

    return _reader


# --------------------------------------------------------------------- device

_MOBILE = re.compile(r"android|iphone|ipod|windows phone|mobile", re.I)
_TABLET = re.compile(r"ipad|tablet|kindle|silk", re.I)

_BROWSERS = (
    ("Edge", re.compile(r"edg/", re.I)),
    ("Samsung Internet", re.compile(r"samsungbrowser", re.I)),
    ("Opera", re.compile(r"opr/|opera", re.I)),
    ("Chrome", re.compile(r"chrome|crios", re.I)),
    ("Firefox", re.compile(r"firefox|fxios", re.I)),
    ("Safari", re.compile(r"safari", re.I)),
)

_OSES = (
    ("Android", re.compile(r"android", re.I)),
    ("iOS", re.compile(r"iphone|ipad|ipod", re.I)),
    ("Windows", re.compile(r"windows", re.I)),
    ("macOS", re.compile(r"mac os x|macintosh", re.I)),
    ("Linux", re.compile(r"linux", re.I)),
)


def parse_device(user_agent: str) -> dict[str, str]:
    """Coarse device, browser and OS. Enough to see mobile vs desktop split."""
    if not user_agent:
        return {"device_type": "", "browser": "", "os": ""}

    if _TABLET.search(user_agent):
        device = "tablet"
    elif _MOBILE.search(user_agent):
        device = "mobile"
    else:
        device = "desktop"

    browser = next((name for name, pattern in _BROWSERS if pattern.search(user_agent)), "")
    os_name = next((name for name, pattern in _OSES if pattern.search(user_agent)), "")

    return {"device_type": device, "browser": browser, "os": os_name}
