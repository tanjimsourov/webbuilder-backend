"""CMS domain API routes."""

from __future__ import annotations

from django.urls import include, path
from rest_framework.routers import SimpleRouter

from cms.views import (
    AssetUsageReferenceViewSet,
    BlockTemplateViewSet,
    MediaAssetViewSet,
    MediaFolderViewSet,
    NavigationMenuViewSet,
    PageExperimentViewSet,
    PageRevisionViewSet,
    PageReviewCommentViewSet,
    PageReviewViewSet,
    PageTranslationViewSet,
    PageViewSet,
    PreviewTokenViewSet,
    PublishSnapshotViewSet,
    ReusableSectionViewSet,
    PublicRuntimeNavigationView,
    PublicRuntimePageLookupView,
    PublicRuntimeRobotsView,
    PublicRuntimeSEOView,
    PublicRuntimeSiteLookupView,
    PublicRuntimeSiteSettingsView,
    PublicRuntimeSitemapView,
    RobotsTxtViewSet,
    SiteShellViewSet,
    ThemeTemplateViewSet,
    URLRedirectViewSet,
)

router = SimpleRouter()
router.register("pages", PageViewSet, basename="page")
router.register("page-translations", PageTranslationViewSet, basename="page-translation")
router.register("page-experiments", PageExperimentViewSet, basename="page-experiment")
router.register("page-reviews", PageReviewViewSet, basename="page-review")
router.register("page-review-comments", PageReviewCommentViewSet, basename="page-review-comment")
router.register("revisions", PageRevisionViewSet, basename="revision")
router.register("media", MediaAssetViewSet, basename="media")
router.register("media-folders", MediaFolderViewSet, basename="media-folder")
router.register("asset-usage", AssetUsageReferenceViewSet, basename="asset-usage")
router.register("block-templates", BlockTemplateViewSet, basename="block-template")
router.register("reusable-sections", ReusableSectionViewSet, basename="reusable-section")
router.register("theme-templates", ThemeTemplateViewSet, basename="theme-template")
router.register("site-shells", SiteShellViewSet, basename="site-shell")
router.register("publish-snapshots", PublishSnapshotViewSet, basename="publish-snapshot")
router.register("preview-tokens", PreviewTokenViewSet, basename="preview-token")
router.register("redirects", URLRedirectViewSet, basename="redirect")
router.register("navigation-menus", NavigationMenuViewSet, basename="navigation-menu")
router.register("robots-txt", RobotsTxtViewSet, basename="robots-txt")

urlpatterns = [
    # Public read-only headless runtime API for Next.js site rendering.
    path("public/runtime/site/", PublicRuntimeSiteLookupView.as_view(), name="runtime-site-lookup"),
    path("public/runtime/page/", PublicRuntimePageLookupView.as_view(), name="runtime-page-lookup"),
    path("public/runtime/navigation/", PublicRuntimeNavigationView.as_view(), name="runtime-navigation"),
    path("public/runtime/settings/", PublicRuntimeSiteSettingsView.as_view(), name="runtime-site-settings"),
    path("public/runtime/seo/", PublicRuntimeSEOView.as_view(), name="runtime-seo"),
    path("public/runtime/robots/", PublicRuntimeRobotsView.as_view(), name="runtime-robots"),
    path("public/runtime/sitemap/", PublicRuntimeSitemapView.as_view(), name="runtime-sitemap"),
    path("", include(router.urls)),
]

