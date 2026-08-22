"""Removes Thrissur references from published blog content.

Ithihasam serves Kannur district only: there is no Thrissur service area,
location page, or landing page anywhere on the site. Titles and body copy that
promise Thrissur coverage create a relevance mismatch — the page cannot satisfy
a Thrissur query — and misrepresent the service area to customers.

Slugs are deliberately left alone. Five posts carry "thrissur" in their URL, and
rewriting those would break existing links and any accumulated ranking without a
redirect layer to catch them. Slug text is a weak signal compared with the
title, headings, and body this migration corrects.
"""

from django.db import migrations


# Ordered longest-first so compound phrases resolve before bare mentions.
REPLACEMENTS = [
    ("Kannur and Thrissur districts", "Kannur district"),
    ("Kannur & Thrissur districts", "Kannur district"),
    ("Kannur and Thrissur", "Kannur"),
    ("Kannur & Thrissur", "Kannur"),
    ("Kannur or Thrissur", "Kannur"),
    ("Kannur, Thrissur", "Kannur"),
    ("Thrissur and Kannur", "Kannur"),
    ("AC repair Thrissur", "AC repair Thalassery"),
    ("electrician in Thrissur", "electrician in Thalassery"),
    ("plumber in Thrissur", "plumber in Taliparamba"),
    ("in Thrissur", "in Kannur district"),
    ("Thrissur", "Kannur"),
]

# "across both districts" and similar only made sense while two were claimed.
FOLLOW_UPS = [
    ("across both districts", "across Kannur district"),
    ("in both districts", "in Kannur district"),
    ("both districts", "Kannur district"),
    ("these two districts", "Kannur district"),
    ("both these districts", "Kannur district"),
]

FIELDS = ("title", "excerpt", "content", "meta_title", "meta_description")


def rewrite(value):
    if not value:
        return value
    for old, new in REPLACEMENTS + FOLLOW_UPS:
        value = value.replace(old, new)
    return value


def remove_thrissur(apps, schema_editor):
    BlogPost = apps.get_model("finoraapp", "BlogPost")

    for post in BlogPost.objects.all():
        changed = []
        for field in FIELDS:
            original = getattr(post, field)
            updated = rewrite(original)
            if updated != original:
                setattr(post, field, updated)
                changed.append(field)

        if changed:
            post.save(update_fields=changed)


def noop_reverse(apps, schema_editor):
    """Not reversible: the original wording is not recoverable from the result."""


class Migration(migrations.Migration):

    dependencies = [
        ("finoraapp", "0009_update_brand_to_ithihasam"),
    ]

    operations = [
        migrations.RunPython(remove_thrissur, noop_reverse),
    ]
