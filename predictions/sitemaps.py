from django.contrib.sitemaps import Sitemap
from django.urls import reverse
from .models import Tip


class TipSitemap(Sitemap):
    changefreq = "daily"
    priority = 0.8

    def items(self):
        return Tip.objects.all()

    def lastmod(self, obj):
        return obj.created_at

    def location(self, obj):
        # Tip has no get_absolute_url(), so Sitemap's default location()
        # (which calls obj.get_absolute_url()) would raise AttributeError.
        return reverse("tip_detail", args=[obj.pk])


class StaticViewSitemap(Sitemap):
    priority = 0.5
    changefreq = "weekly"

    def items(self):
        # "tips_list" requires a tip_type arg (path("tips/<str:tip_type>/", ...)),
        # so reverse("tips_list") with no args would raise NoReverseMatch.
        # List the two concrete variants instead.
        return ["home", "history", "stats"]

    def location(self, item):
        return reverse(item)


class TipsListSitemap(Sitemap):
    priority = 0.5
    changefreq = "daily"

    def items(self):
        return ["free", "vip"]

    def location(self, tip_type):
        return reverse("tips_list", args=[tip_type])