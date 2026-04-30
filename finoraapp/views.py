from xml.etree.ElementTree import Element, SubElement, tostring

from django.conf import settings
from django.http import HttpResponse
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .models import BlogPost, ContactSubmission
from .notifications import send_booking_notification
from .serializers import (
    BlogPostDetailSerializer,
    BlogPostListSerializer,
    ContactSubmissionSerializer,
)


class PublicAPIViewMixin:
    authentication_classes = []
    permission_classes = [permissions.AllowAny]


STATIC_SITEMAP_ENTRIES = [
    {"path": "/", "priority": "1.0"},
    {"path": "/services", "priority": "0.95"},
    {"path": "/about", "priority": "0.8"},
    {"path": "/contact", "priority": "0.9"},
    {"path": "/blog", "priority": "0.85"},
    {"path": "/news", "priority": "0.8"},
    {"path": "/privacy-policy", "priority": "0.4"},
    {"path": "/terms-and-conditions", "priority": "0.4"},
    {"path": "/services/electrical-plumbing", "priority": "0.9"},
    {"path": "/services/painting", "priority": "0.9"},
    {"path": "/services/appliance-servicing", "priority": "0.9"},
    {"path": "/services/carpentry", "priority": "0.9"},
    {"path": "/services/roofing-fabrication", "priority": "0.85"},
    {"path": "/services/deep-cleaning", "priority": "0.9"},
    {"path": "/services/pest-control", "priority": "0.9"},
    {"path": "/services/smart-home", "priority": "0.85"},
    {"path": "/news/itihasam-expands-to-5-new-cities", "lastmod": "2026-04-08", "priority": "0.7"},
    {"path": "/news/annual-home-cleaning-drive-2026", "lastmod": "2026-03-25", "priority": "0.7"},
    {"path": "/news/new-carpentry-workshop-program", "lastmod": "2026-03-10", "priority": "0.7"},
    {"path": "/locations/thalassery", "priority": "0.85"},
    {"path": "/locations/panoor", "priority": "0.85"},
    {"path": "/locations/nadapuram", "priority": "0.85"},
    {"path": "/locations/mahe", "priority": "0.85"},
    {"path": "/locations/kuthuparamba", "priority": "0.85"},
    {"path": "/locations/mattannur", "priority": "0.85"},
    {"path": "/locations/iritty", "priority": "0.85"},
    {"path": "/locations/chakkarakkal", "priority": "0.85"},
    {"path": "/locations/anjarakandy", "priority": "0.85"},
    {"path": "/locations/chalod", "priority": "0.85"},
    {"path": "/locations/thazhe-chovva", "priority": "0.85"},
    {"path": "/locations/taliparamba", "priority": "0.85"},
    {"path": "/locations/payyannur", "priority": "0.85"},
]

LOCAL_SERVICE_LOCATION_SLUGS = [
    "thalassery",
    "panoor",
    "nadapuram",
    "mahe",
    "kuthuparamba",
    "mattannur",
    "iritty",
    "chakkarakkal",
    "anjarakandy",
    "chalod",
    "thazhe-chovva",
    "taliparamba",
    "payyannur",
]

LOCAL_SERVICE_SLUG_PREFIXES = [
    "appliance-servicing",
    "ac-repair",
    "washing-machine-repair",
    "refrigerator-repair",
    "fridge-repair",
    "appliance-service",
    "electrician",
    "plumber",
    "electrical-plumbing",
    "painting",
    "house-painting",
    "interior-painting",
    "exterior-painting",
    "carpentry",
    "carpenter",
    "furniture-repair",
    "modular-kitchen-work",
    "roofing-fabrication",
    "aluminium-fabrication",
    "steel-fabrication",
    "gate-fabrication",
    "roofing-sheet-work",
    "deep-cleaning",
    "home-cleaning",
    "sofa-cleaning",
    "pest-control",
    "termite-control",
    "cockroach-control",
    "smart-home",
    "cctv-installation",
    "smart-home-setup",
    "wifi-setup",
]

LOCAL_SERVICE_SITEMAP_ENTRIES = [
    {"path": f"/{service_slug}-{location_slug}", "priority": "0.78"}
    for location_slug in LOCAL_SERVICE_LOCATION_SLUGS
    for service_slug in LOCAL_SERVICE_SLUG_PREFIXES
]


def sitemap_xml_view(request):
    urlset = Element("urlset", xmlns="http://www.sitemaps.org/schemas/sitemap/0.9")

    for entry in [*STATIC_SITEMAP_ENTRIES, *LOCAL_SERVICE_SITEMAP_ENTRIES]:
        url = SubElement(urlset, "url")
        SubElement(url, "loc").text = f"{settings.SITE_URL}{entry['path']}"

        if entry.get("lastmod"):
            SubElement(url, "lastmod").text = entry["lastmod"]

        if entry.get("priority"):
            SubElement(url, "priority").text = entry["priority"]

    for post in BlogPost.objects.filter(is_published=True):
        url = SubElement(urlset, "url")
        SubElement(url, "loc").text = f"{settings.SITE_URL}{post.get_absolute_url()}"
        SubElement(url, "lastmod").text = post.updated_at.date().isoformat()
        SubElement(url, "priority").text = "0.8"

    xml_content = tostring(urlset, encoding="utf-8", xml_declaration=True)
    return HttpResponse(xml_content, content_type="application/xml")


class HealthCheckAPIView(PublicAPIViewMixin, APIView):
    def get(self, request, *args, **kwargs):
        return Response({"status": "ok"})


class BlogPostListAPIView(PublicAPIViewMixin, generics.ListAPIView):
    serializer_class = BlogPostListSerializer

    def get_queryset(self):
        return BlogPost.objects.filter(is_published=True)


class BlogPostDetailAPIView(PublicAPIViewMixin, generics.RetrieveAPIView):
    serializer_class = BlogPostDetailSerializer
    lookup_field = "slug"

    def get_queryset(self):
        return BlogPost.objects.filter(is_published=True)


class ContactSubmissionCreateAPIView(PublicAPIViewMixin, generics.CreateAPIView):
    queryset = ContactSubmission.objects.all()
    serializer_class = ContactSubmissionSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "contact_submissions"

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        notification_sent = send_booking_notification(serializer.instance)
        headers = self.get_success_headers(serializer.data)
        return Response(
            {
                "message": "Thank you! Your booking request has been received.",
                "notification_sent": notification_sent,
                "submission": serializer.data,
            },
            status=status.HTTP_201_CREATED,
            headers=headers,
        )
