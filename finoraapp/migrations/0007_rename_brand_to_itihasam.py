from django.db import migrations


def rename_brand_to_itihasam(apps, schema_editor):
    BlogPost = apps.get_model("finoraapp", "BlogPost")

    for post in BlogPost.objects.all():
        changed = False

        for field_name in ("title", "excerpt", "content", "author_name", "meta_title", "meta_description"):
            value = getattr(post, field_name, "")
            if value and "Ithihasa" in value:
                setattr(post, field_name, value.replace("Ithihasa", "Itihasam"))
                changed = True

        if changed:
            post.save(
                update_fields=[
                    "title",
                    "excerpt",
                    "content",
                    "author_name",
                    "meta_title",
                    "meta_description",
                ]
            )


class Migration(migrations.Migration):
    dependencies = [
        ("finoraapp", "0006_seed_local_seo_blog_posts"),
    ]

    operations = [
        migrations.RunPython(rename_brand_to_itihasam, migrations.RunPython.noop),
    ]
