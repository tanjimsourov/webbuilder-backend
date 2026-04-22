"""Blog domain serializers plus runtime-safe public serializers."""

from __future__ import annotations

from rest_framework import serializers

from blog.models import BlogAuthor, Post, PostCategory, PostTag

from builder.serializers import (  # noqa: F401
    BlogAuthorSerializer,
    CommentSerializer,
    PostCategorySerializer,
    PostSerializer,
    PostTagSerializer,
    PublicCommentSubmissionSerializer,
)


class PublicRuntimePostCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = PostCategory
        fields = ["slug", "name"]


class PublicRuntimePostTagSerializer(serializers.ModelSerializer):
    class Meta:
        model = PostTag
        fields = ["slug", "name"]


class PublicRuntimePostSerializer(serializers.ModelSerializer):
    """Published-only blog payload for the Next.js runtime."""

    categories = PublicRuntimePostCategorySerializer(many=True, read_only=True)
    tags = PublicRuntimePostTagSerializer(many=True, read_only=True)
    primary_author = serializers.SerializerMethodField()
    related_posts = serializers.SerializerMethodField()
    featured_image_url = serializers.SerializerMethodField()

    class Meta:
        model = Post
        fields = [
            "id",
            "title",
            "slug",
            "excerpt",
            "body_html",
            "seo",
            "published_at",
            "updated_at",
            "primary_author",
            "related_posts",
            "categories",
            "tags",
            "featured_image_url",
        ]

    def _serialize_author(self, author: BlogAuthor | None) -> dict:
        if author is None:
            return {}
        return {
            "id": author.id,
            "display_name": author.display_name,
            "slug": author.slug,
            "avatar_url": author.avatar_url,
            "bio": author.bio,
        }

    def get_primary_author(self, obj: Post) -> dict:
        return self._serialize_author(obj.primary_author)

    def get_related_posts(self, obj: Post) -> list[dict]:
        now = obj.updated_at
        related = (
            obj.related_posts.filter(status=Post.STATUS_PUBLISHED)
            .exclude(pk=obj.pk)
            .order_by("-published_at", "-updated_at")[:4]
        )
        return [
            {
                "id": related_post.id,
                "slug": related_post.slug,
                "title": related_post.title,
                "excerpt": related_post.excerpt,
                "published_at": related_post.published_at or now,
            }
            for related_post in related
        ]

    def get_featured_image_url(self, obj: Post) -> str:
        if not obj.featured_media_id or not obj.featured_media.file:
            return ""
        request = self.context.get("request")
        url = obj.featured_media.file.url
        return request.build_absolute_uri(url) if request else url


__all__ = [
    "BlogAuthorSerializer",
    "CommentSerializer",
    "PostCategorySerializer",
    "PostSerializer",
    "PostTagSerializer",
    "PublicCommentSubmissionSerializer",
    "PublicRuntimePostCategorySerializer",
    "PublicRuntimePostSerializer",
    "PublicRuntimePostTagSerializer",
]
