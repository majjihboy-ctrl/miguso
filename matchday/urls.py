from django.contrib import admin
from django.urls import path, include
from django.views.generic import TemplateView
from django.contrib.sitemaps.views import sitemap
from predictions.sitemaps import TipSitemap, StaticViewSitemap, TipsListSitemap
from predictions.views import RateLimitedLoginView

sitemaps = {
    "tips": TipSitemap,
    "static": StaticViewSitemap,
    "tips_list": TipsListSitemap,
}

urlpatterns = [
    path("admin/", admin.site.urls),
    # Override the default LoginView from django.contrib.auth.urls with a
    # rate-limited version; must be listed before the include() below so
    # it takes precedence.
    path("accounts/login/", RateLimitedLoginView.as_view(), name="login"),
    path("accounts/", include("django.contrib.auth.urls")),
    path("", include("predictions.urls")),
    path("robots.txt", TemplateView.as_view(template_name="robots.txt", content_type="text/plain")),
    path("sitemap.xml", sitemap, {"sitemaps": sitemaps}, name="django.contrib.sitemaps.views.sitemap"),
]