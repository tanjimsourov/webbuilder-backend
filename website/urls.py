from __future__ import annotations

from django.urls import path

from website.views import (
    WebsiteDomainVerifyView,
    WebsiteDomainsView,
    WebsitePublishStatusView,
    WebsiteRobotsView,
    WebsiteSettingsView,
    WebsiteSitemapView,
)

urlpatterns = [
    path("website/sites/<int:site_id>/settings/", WebsiteSettingsView.as_view(), name="website-settings"),
    path("website/sites/<int:site_id>/publish-status/", WebsitePublishStatusView.as_view(), name="website-publish-status"),
    path("website/sites/<int:site_id>/domains/", WebsiteDomainsView.as_view(), name="website-domains"),
    path(
        "website/sites/<int:site_id>/domains/<int:domain_id>/verify/",
        WebsiteDomainVerifyView.as_view(),
        name="website-domain-verify",
    ),
    path("website/sites/<int:site_id>/robots/", WebsiteRobotsView.as_view(), name="website-robots"),
    path("website/sites/<int:site_id>/sitemap/", WebsiteSitemapView.as_view(), name="website-sitemap"),
]

