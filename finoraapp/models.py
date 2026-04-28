from django.db import models
from django.utils.html import strip_tags
from django.utils.text import Truncator, slugify


DEFAULT_BLOG_AUTHOR = "Ithihasam Editorial Team"


class BlogPost(models.Model):
    title = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True)
    excerpt = models.TextField()
    category = models.CharField(max_length=50, db_index=True)
    cover_image = models.ImageField(upload_to="blog/covers/", blank=True, default="")
    content = models.TextField()
    author_name = models.CharField(max_length=100, default=DEFAULT_BLOG_AUTHOR)
    meta_title = models.CharField(max_length=255, blank=True)
    meta_description = models.TextField(blank=True)
    read_time_minutes = models.PositiveSmallIntegerField(default=5)
    published_at = models.DateField(db_index=True)
    featured = models.BooleanField(default=False)
    is_published = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-published_at", "-id")

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title)
        if not self.author_name:
            self.author_name = DEFAULT_BLOG_AUTHOR
        if not self.meta_title:
            self.meta_title = self.title
        if not self.meta_description:
            summary_source = self.excerpt or strip_tags(self.content)
            self.meta_description = Truncator(summary_source).chars(160)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return f"/blog/{self.slug}"

    def __str__(self):
        return self.title


class ContactSubmission(models.Model):
    name = models.CharField(max_length=100)
    email = models.EmailField(max_length=255, blank=True, default="")
    phone = models.CharField(max_length=30)
    whatsapp = models.CharField(max_length=30, blank=True, default="")
    service = models.CharField(max_length=100)
    city = models.CharField(max_length=100, blank=True, default="")
    preferred_date = models.DateField(null=True, blank=True)
    subject = models.CharField(max_length=200, blank=True, default="")
    message = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at", "-id")

    def __str__(self):
        return f"{self.name} - {self.service}"
