from django.conf import settings
from django.contrib import admin
from django.conf.urls.static import static
from django.urls import include, path

from finoraapp.views import sitemap_xml_view

urlpatterns = [
    path("sitemap.xml", sitemap_xml_view, name="sitemap-xml"),
    path("ckeditor5/", include("django_ckeditor_5.urls")),
    path("admin/", admin.site.urls),
    path("api/", include("finoraapp.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
