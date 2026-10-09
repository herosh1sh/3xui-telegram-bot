from django.urls import include, path, re_path
from django.views.static import serve
from django.conf import settings

urlpatterns = [
    path("", include("cabinet.urls")),
    re_path(r"^assets/(?P<path>.*)$", serve, {"document_root": settings.FRONTEND_DIST / "assets"}),
]
