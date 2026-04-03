"""CMS domain view wrappers.

These classes currently inherit behavior from ``builder.views`` and provide
the app-local extension points for CMS logic.
"""

from __future__ import annotations

from builder.views import (
    BlockTemplateViewSet as BuilderBlockTemplateViewSet,
    DomainContactViewSet,
    DomainViewSet,
    MediaAssetViewSet as BuilderMediaAssetViewSet,
    MediaFolderViewSet as BuilderMediaFolderViewSet,
    NavigationMenuViewSet as BuilderNavigationMenuViewSet,
    PageExperimentViewSet,
    PageRevisionViewSet,
    PageReviewCommentViewSet,
    PageReviewViewSet,
    PageTranslationViewSet as BuilderPageTranslationViewSet,
    PageViewSet as BuilderPageViewSet,
    RobotsTxtViewSet as BuilderRobotsTxtViewSet,
    URLRedirectViewSet as BuilderURLRedirectViewSet,
    public_page,
    public_robots,
    public_sitemap,
)


class PageViewSet(BuilderPageViewSet):
    """CMS page endpoints."""


class PageTranslationViewSet(BuilderPageTranslationViewSet):
    """Localized page endpoints."""


class MediaAssetViewSet(BuilderMediaAssetViewSet):
    """Media asset endpoints."""


class MediaFolderViewSet(BuilderMediaFolderViewSet):
    """Media folder endpoints."""


class BlockTemplateViewSet(BuilderBlockTemplateViewSet):
    """Reusable block template endpoints."""


class URLRedirectViewSet(BuilderURLRedirectViewSet):
    """Redirect management endpoints."""


class NavigationMenuViewSet(BuilderNavigationMenuViewSet):
    """Navigation menu endpoints."""


class RobotsTxtViewSet(BuilderRobotsTxtViewSet):
    """robots.txt endpoints."""


__all__ = [
    "BlockTemplateViewSet",
    "DomainContactViewSet",
    "DomainViewSet",
    "MediaAssetViewSet",
    "MediaFolderViewSet",
    "NavigationMenuViewSet",
    "PageExperimentViewSet",
    "PageRevisionViewSet",
    "PageReviewCommentViewSet",
    "PageReviewViewSet",
    "PageTranslationViewSet",
    "PageViewSet",
    "RobotsTxtViewSet",
    "URLRedirectViewSet",
    "public_page",
    "public_robots",
    "public_sitemap",
]
