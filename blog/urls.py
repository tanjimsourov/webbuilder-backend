"""Blog domain API routes."""

from __future__ import annotations

from django.urls import include, path
from rest_framework.routers import SimpleRouter

from blog.views import (
    BlogAuthorViewSet,
    CommentViewSet,
    PostCategoryViewSet,
    PostTagViewSet,
    PostViewSet,
    PublicCommentSubmissionView,
    PublicRuntimeBlogPostDetailView,
    PublicRuntimeBlogPostsView,
)

router = SimpleRouter()
router.register("post-categories", PostCategoryViewSet, basename="post-category")
router.register("post-tags", PostTagViewSet, basename="post-tag")
router.register("authors", BlogAuthorViewSet, basename="blog-author")
router.register("posts", PostViewSet, basename="post")
router.register("comments", CommentViewSet, basename="comment")

urlpatterns = [
    path("public/comments/submit/", PublicCommentSubmissionView.as_view(), name="public-comment-submit"),
    path("public/runtime/blog/posts/", PublicRuntimeBlogPostsView.as_view(), name="runtime-blog-posts"),
    path(
        "public/runtime/blog/posts/<slug:post_slug>/",
        PublicRuntimeBlogPostDetailView.as_view(),
        name="runtime-blog-post-detail",
    ),
    path("", include(router.urls)),
]

