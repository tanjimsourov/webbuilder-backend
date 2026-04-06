"""Blog domain serializers plus runtime-safe public serializers."""

from __future__ import annotations

from rest_framework import serializers

from blog.models import Post, PostCategory, PostTag

from builder.serializers import (  # noqa: F401
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
            "categories",
            "tags",
            "featured_image_url",
        ]

    def get_featured_image_url(self, obj: Post) -> str:
        if not obj.featured_media_id or not obj.featured_media.file:
            return ""
        request = self.context.get("request")
        url = obj.featured_media.file.url
        return request.build_absolute_uri(url) if request else url


__all__ = [
    "CommentSerializer",
    "PostCategorySerializer",
    "PostSerializer",
    "PostTagSerializer",
    "PublicCommentSubmissionSerializer",
    "PublicRuntimePostCategorySerializer",
    "PublicRuntimePostSerializer",
    "PublicRuntimePostTagSerializer",
]
