"""Blog domain view wrappers."""

from __future__ import annotations

from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from blog.models import Post
from blog.serializers import PublicRuntimePostSerializer
from cms.services import public_site_capabilities
from builder.views import (
    BlogAuthorViewSet as BuilderBlogAuthorViewSet,
    CommentViewSet as BuilderCommentViewSet,
    PostCategoryViewSet as BuilderPostCategoryViewSet,
    PostTagViewSet as BuilderPostTagViewSet,
    PostViewSet as BuilderPostViewSet,
    PublicCommentSubmissionView,
    SiteBlogFeed,
    public_blog_index,
    public_blog_post,
)
from django.utils.cache import patch_cache_control
from core.views import PublicRuntimeSiteMixin


PostViewSet = BuilderPostViewSet
PostCategoryViewSet = BuilderPostCategoryViewSet
PostTagViewSet = BuilderPostTagViewSet
BlogAuthorViewSet = BuilderBlogAuthorViewSet
CommentViewSet = BuilderCommentViewSet


class PublicRuntimeBlogPostsView(PublicRuntimeSiteMixin, APIView):
    """Published blog listing endpoint for headless runtime consumption."""

    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def get(self, request):
        site, _ = self.resolve_public_site(request)
        capabilities = public_site_capabilities(site)
        if not capabilities.get("blog_enabled", False):
            return Response({"site": {"id": site.id, "slug": site.slug}, "results": []})

        now = timezone.now()
        queryset = (
            site.posts.select_related("featured_media", "primary_author")
            .prefetch_related("categories", "tags", "related_posts")
            .filter(status=Post.STATUS_PUBLISHED)
            .filter(Q(published_at__isnull=True) | Q(published_at__lte=now))
            .order_by("-published_at", "-updated_at")
        )

        category = (request.query_params.get("category") or "").strip()
        tag = (request.query_params.get("tag") or "").strip()
        query = (request.query_params.get("q") or "").strip()
        if category:
            queryset = queryset.filter(categories__slug=category)
        if tag:
            queryset = queryset.filter(tags__slug=tag)
        if query:
            queryset = queryset.filter(Q(title__icontains=query) | Q(excerpt__icontains=query) | Q(body_html__icontains=query))

        try:
            limit = max(1, min(int(request.query_params.get("limit", 20)), 100))
        except (TypeError, ValueError):
            limit = 20
        posts = list(queryset[:limit])
        serializer = PublicRuntimePostSerializer(posts, many=True, context={"request": request})
        response = Response(
            {
                "site": {"id": site.id, "slug": site.slug},
                "count": len(posts),
                "results": serializer.data,
            }
        )
        patch_cache_control(response, public=True, max_age=60, s_maxage=300, stale_while_revalidate=60)
        return response


class PublicRuntimeBlogPostDetailView(PublicRuntimeSiteMixin, APIView):
    """Single published blog post endpoint for headless runtime rendering."""

    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def get(self, request, post_slug: str):
        site, _ = self.resolve_public_site(request)
        capabilities = public_site_capabilities(site)
        if not capabilities.get("blog_enabled", False):
            return Response({"detail": "Blog is disabled for this site."}, status=404)

        now = timezone.now()
        post = get_object_or_404(
            site.posts.select_related("featured_media", "primary_author").prefetch_related("categories", "tags", "related_posts"),
            slug=post_slug,
            status=Post.STATUS_PUBLISHED,
        )
        if post.published_at and post.published_at > now:
            return Response({"detail": "Published post not found."}, status=404)

        serializer = PublicRuntimePostSerializer(post, context={"request": request})
        response = Response(
            {
                "site": {"id": site.id, "slug": site.slug},
                "post": serializer.data,
            }
        )
        patch_cache_control(response, public=True, max_age=60, s_maxage=300, stale_while_revalidate=60)
        return response


__all__ = [
    "CommentViewSet",
    "BlogAuthorViewSet",
    "PostCategoryViewSet",
    "PostTagViewSet",
    "PostViewSet",
    "PublicCommentSubmissionView",
    "PublicRuntimeBlogPostDetailView",
    "PublicRuntimeBlogPostsView",
    "SiteBlogFeed",
    "public_blog_index",
    "public_blog_post",
]
