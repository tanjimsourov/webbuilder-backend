"""Blog domain view wrappers."""

from __future__ import annotations

from builder.views import (
    CommentViewSet as BuilderCommentViewSet,
    PostCategoryViewSet as BuilderPostCategoryViewSet,
    PostTagViewSet as BuilderPostTagViewSet,
    PostViewSet as BuilderPostViewSet,
    PublicCommentSubmissionView,
    SiteBlogFeed,
    public_blog_index,
    public_blog_post,
)


class PostViewSet(BuilderPostViewSet):
    """Blog post endpoints."""


class PostCategoryViewSet(BuilderPostCategoryViewSet):
    """Blog category endpoints."""


class PostTagViewSet(BuilderPostTagViewSet):
    """Blog tag endpoints."""


class CommentViewSet(BuilderCommentViewSet):
    """Blog comment moderation endpoints."""


__all__ = [
    "CommentViewSet",
    "PostCategoryViewSet",
    "PostTagViewSet",
    "PostViewSet",
    "PublicCommentSubmissionView",
    "SiteBlogFeed",
    "public_blog_index",
    "public_blog_post",
]
