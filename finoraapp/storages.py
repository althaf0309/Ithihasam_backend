from django.conf import settings
from django.core.files.storage import FileSystemStorage


class CKEditor5Storage(FileSystemStorage):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("location", settings.MEDIA_ROOT / "ckeditor")
        kwargs.setdefault("base_url", f"{settings.MEDIA_URL.rstrip('/')}/ckeditor/")
        super().__init__(*args, **kwargs)
