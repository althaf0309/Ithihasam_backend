from django.db import migrations, models


def rename_brand_references(apps, schema_editor):
    BlogPost = apps.get_model("finoraapp", "BlogPost")
    text_fields = (
        "title",
        "excerpt",
        "content",
        "meta_title",
        "meta_description",
        "author_name",
    )

    for post in BlogPost.objects.all():
        updated_fields = []
        for field_name in text_fields:
            value = getattr(post, field_name, "")
            if value and "Itihasam" in value:
                setattr(post, field_name, value.replace("Itihasam", "Ithihasam"))
                updated_fields.append(field_name)

        if updated_fields:
            post.save(update_fields=updated_fields)


class Migration(migrations.Migration):

    dependencies = [
        ("finoraapp", "0008_alter_blogpost_author_name"),
    ]

    operations = [
        migrations.AlterField(
            model_name="blogpost",
            name="author_name",
            field=models.CharField(default="Ithihasam Editorial Team", max_length=100),
        ),
        migrations.RunPython(rename_brand_references, migrations.RunPython.noop),
    ]
