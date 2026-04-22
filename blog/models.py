"""Blog app models."""

from __future__ import annotations

from django.conf import settings
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


class BlogAuthor(TimeStampedModel):
    site = models.ForeignKey(Site, related_name="blog_authors", on_delete=models.CASCADE)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="blog_author_profiles",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    display_name = models.CharField(max_length=160)
    slug = models.SlugField(max_length=180)
    bio = models.TextField(blank=True)
    avatar_url = models.URLField(blank=True)
    is_active = models.BooleanField(default=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["display_name"]
        constraints = [
            models.UniqueConstraint(fields=["site", "slug"], name="blog_unique_site_author_slug"),
        ]

    def __str__(self) -> str:
        return f"{self.site.name}: {self.display_name}"


class Post(TimeStampedModel):
    STATUS_DRAFT = "draft"
    STATUS_IN_REVIEW = "in_review"
    STATUS_SCHEDULED = "scheduled"
    STATUS_PUBLISHED = "published"
    STATUS_ARCHIVED = "archived"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_IN_REVIEW, "In review"),
        (STATUS_SCHEDULED, "Scheduled"),
        (STATUS_PUBLISHED, "Published"),
        (STATUS_ARCHIVED, "Archived"),
    ]

    site = models.ForeignKey(Site, related_name="posts", on_delete=models.CASCADE)
    title = models.CharField(max_length=180)
    slug = models.SlugField(max_length=180)
    excerpt = models.TextField(blank=True)
    body_html = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    featured_media = models.ForeignKey(
        "cms.MediaAsset",
        related_name="featured_posts",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    primary_author = models.ForeignKey(
        BlogAuthor,
        related_name="primary_posts",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    author_byline = models.CharField(max_length=160, blank=True)
    categories = models.ManyToManyField(PostCategory, related_name="posts", blank=True)
    tags = models.ManyToManyField(PostTag, related_name="posts", blank=True)
    related_posts = models.ManyToManyField(
        "self",
        symmetrical=False,
        related_name="related_to_posts",
        blank=True,
    )
    seo = models.JSONField(default=dict, blank=True)
    published_at = models.DateTimeField(blank=True, null=True)
    scheduled_at = models.DateTimeField(blank=True, null=True, help_text="Schedule publish time")
    moderation_notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-published_at", "-updated_at", "title"]
        constraints = [
            models.UniqueConstraint(fields=["site", "slug"], name="blog_unique_site_post_slug"),
        ]

    def __str__(self) -> str:
        return f"{self.site.name}: {self.title}"


class Comment(TimeStampedModel):
    MODERATION_PENDING = "pending"
    MODERATION_APPROVED = "approved"
    MODERATION_REJECTED = "rejected"
    MODERATION_SPAM = "spam"
    MODERATION_CHOICES = [
        (MODERATION_PENDING, "Pending"),
        (MODERATION_APPROVED, "Approved"),
        (MODERATION_REJECTED, "Rejected"),
        (MODERATION_SPAM, "Spam"),
    ]

    post = models.ForeignKey(Post, related_name="comments", on_delete=models.CASCADE)
    author_name = models.CharField(max_length=140)
    author_email = models.EmailField()
    body = models.TextField()
    is_approved = models.BooleanField(default=False)
    moderation_state = models.CharField(max_length=20, choices=MODERATION_CHOICES, default=MODERATION_PENDING)
    moderation_notes = models.TextField(blank=True)
    spam_score = models.FloatField(default=0.0)
    spam_provider = models.CharField(max_length=80, blank=True)
    flagged_at = models.DateTimeField(blank=True, null=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.post.title}: {self.author_name}"
