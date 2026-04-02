"""Blog app models."""

from __future__ import annotations

from django.db import models

from core.models import Site, TimeStampedModel


class PostCategory(TimeStampedModel):
    site = models.ForeignKey(Site, related_name="post_categories", on_delete=models.CASCADE)
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["site", "slug"], name="blog_unique_site_post_category_slug"),
        ]

    def __str__(self) -> str:
        return f"{self.site.name}: {self.name}"


class PostTag(TimeStampedModel):
    site = models.ForeignKey(Site, related_name="post_tags", on_delete=models.CASCADE)
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["site", "slug"], name="blog_unique_site_post_tag_slug"),
        ]

    def __str__(self) -> str:
        return f"{self.site.name}: {self.name}"


class Post(TimeStampedModel):
    STATUS_DRAFT = "draft"
    STATUS_PUBLISHED = "published"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_PUBLISHED, "Published"),
    ]

    site = models.ForeignKey(Site, related_name="posts", on_delete=models.CASCADE)
    title = models.CharField(max_length=180)
    slug = models.SlugField(max_length=180)
    excerpt = models.TextField(blank=True)
    body_html = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    featured_media = models.ForeignKey(
        "builder.MediaAsset",
        related_name="featured_posts",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    categories = models.ManyToManyField(PostCategory, related_name="posts", blank=True)
    tags = models.ManyToManyField(PostTag, related_name="posts", blank=True)
    seo = models.JSONField(default=dict, blank=True)
    published_at = models.DateTimeField(blank=True, null=True)
    scheduled_at = models.DateTimeField(blank=True, null=True, help_text="Schedule publish time")

    class Meta:
        ordering = ["-published_at", "-updated_at", "title"]
        constraints = [
            models.UniqueConstraint(fields=["site", "slug"], name="blog_unique_site_post_slug"),
        ]

    def __str__(self) -> str:
        return f"{self.site.name}: {self.title}"


class Comment(TimeStampedModel):
    post = models.ForeignKey(Post, related_name="comments", on_delete=models.CASCADE)
    author_name = models.CharField(max_length=140)
    author_email = models.EmailField()
    body = models.TextField()
    is_approved = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.post.title}: {self.author_name}"
