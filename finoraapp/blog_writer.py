"""Writes a blog post for a planned topic using the Claude API.

The brief is assembled from the site's own data — the town's terrain and
access, the service's real item list and any compliance obligation — so the
post states facts the business can stand behind rather than inventing detail.

Posts are returned as structured data and saved as drafts. Nothing publishes
without a person approving it.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from django.conf import settings

from .blog_planner import Topic

logger = logging.getLogger(__name__)

#: Claude Haiku 5.5 is the right tier here: the brief carries the facts, so
#: the model is arranging known material rather than reasoning hard about it.
#: At $0.10/$0.50 per MTok a ~1,200 word post costs well under a rupee.
DEFAULT_MODEL = "claude-haiku-5-5"

SYSTEM_PROMPT = """You write for Ithihasam, a home maintenance and construction \
business in Kerala, India. You are writing one blog post.

Rules you must follow:

- Use ONLY the facts in the brief. Do not invent prices, timelines, project \
counts, customer names, testimonials, awards, or years in business.
- Never state a specific rupee figure unless the brief gives one. Say what \
changes the cost instead.
- Write for a homeowner or small builder in Kerala. Plain English, short \
sentences. Assume they know the area but not the trade.
- Be specific to the town named. A post that would read the same with another \
town's name swapped in has failed.
- If the brief carries a compliance note, state it plainly. Do not soften it.
- No marketing superlatives: no "best", "leading", "trusted", "premier", \
"one-stop".
- Do not open with "In today's world", "When it comes to", or similar filler.

Return ONLY a JSON object, no prose around it, with these keys:
  title            60 characters or fewer, includes the town name
  slug             lowercase, hyphenated, 70 characters or fewer
  excerpt          one or two sentences, 140-180 characters
  meta_title       60 characters or fewer
  meta_description 150-158 characters
  content          the post in Markdown, 700-1100 words
  read_time        whole number of minutes

The content must use ## subheadings, and must end with a short section telling \
the reader they can call or WhatsApp for a quote on their own job."""


@dataclass
class WrittenPost:
    title: str
    slug: str
    excerpt: str
    meta_title: str
    meta_description: str
    content: str
    read_time: int


def build_brief(topic: Topic) -> str:
    """The facts handed to the model, drawn from the site's own data."""
    town = topic.facts.get("town", {})
    service = topic.facts.get("service", {})

    lines = [
        f"Service: {topic.service_name}",
        f"Town: {topic.place_name}",
        f"Angle: {topic.angle_label}",
        "",
    ]

    if service.get("intro"):
        lines.append(f"What this service is: {service['intro']}")
    if service.get("items"):
        lines.append("What it covers: " + "; ".join(service["items"]))
    if service.get("compliance"):
        lines.append(f"LEGAL OBLIGATION, state this plainly: {service['compliance']}")

    if town:
        lines.append("")
        lines.append(f"About {topic.place_name}:")
        for key, label in (
            ("district", "District"),
            ("terrain", "Ground conditions"),
            ("access", "Site access"),
            ("building", "What gets built there"),
            ("note", "Local detail worth stating"),
        ):
            if town.get(key):
                lines.append(f"  {label}: {town[key]}")

    lines += [
        "",
        "Contact details to use in the closing section:",
        f"  Phone and WhatsApp: {getattr(settings, 'BUSINESS_PHONE', '+91 94000 96518')}",
        "  The business quotes per job after understanding the scope.",
    ]

    return "\n".join(lines)


def _extract_json(text: str) -> dict:
    """Parses the model's reply, tolerating a markdown code fence around it."""
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fenced:
        text = fenced.group(1)

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in the model's reply")

    return json.loads(text[start : end + 1])


def write_post(topic: Topic, *, model: str | None = None) -> WrittenPost:
    """Calls the Claude API and returns the post.

    Raises on any failure so the caller can skip this topic and carry on with
    the rest of the batch rather than aborting the whole run.
    """
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover - depends on the install
        raise RuntimeError(
            "The anthropic package is not installed. Run: pip install anthropic"
        ) from exc

    api_key = getattr(settings, "ANTHROPIC_API_KEY", "")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set in the environment.")

    client = anthropic.Anthropic(api_key=api_key)

    response = client.messages.create(
        model=model or getattr(settings, "BLOG_MODEL", DEFAULT_MODEL),
        max_tokens=4000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": build_brief(topic)}],
    )

    # A safety classifier can decline; the content list is then not a post.
    if response.stop_reason == "refusal":
        raise RuntimeError(f"the model declined to write {topic.key}")

    text = "".join(block.text for block in response.content if block.type == "text")
    data = _extract_json(text)

    missing = [
        key
        for key in ("title", "slug", "excerpt", "meta_description", "content")
        if not data.get(key)
    ]
    if missing:
        raise ValueError(f"the reply is missing {', '.join(missing)}")

    logger.info(
        "wrote %s (%s in, %s out tokens)",
        topic.key,
        response.usage.input_tokens,
        response.usage.output_tokens,
    )

    return WrittenPost(
        title=data["title"].strip()[:255],
        slug=re.sub(r"[^a-z0-9-]+", "-", data["slug"].lower()).strip("-")[:255],
        excerpt=data["excerpt"].strip(),
        meta_title=(data.get("meta_title") or data["title"]).strip()[:255],
        meta_description=data["meta_description"].strip(),
        content=data["content"].strip(),
        read_time=int(data.get("read_time") or 5),
    )
