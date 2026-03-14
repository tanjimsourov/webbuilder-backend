from django.contrib import admin

from .models import (
    BlockTemplate,
    Cart,
    CartItem,
    Comment,
    DiscountCode,
    Domain,
    DomainAvailability,
    DomainContact,
    ExperimentEvent,
    FormSubmission,
    MediaAsset,
    MediaFolder,
    NavigationMenu,
    Order,
    OrderItem,
    Page,
    PageExperiment,
    PageExperimentVariant,
    PageReview,
    PageReviewComment,
    PageRevision,
    PlatformEmailCampaign,
    PlatformOffer,
    PlatformSubscription,
    Post,
    PostCategory,
    PostTag,
    Product,
    ProductCategory,
    ProductVariant,
    RobotsTxt,
    SEOAnalytics,
    ShippingRate,
    ShippingZone,
    Site,
    TaxRate,
    URLRedirect,
    Webhook,
)


@admin.register(Site)
class SiteAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "domain", "updated_at")
    search_fields = ("name", "slug", "domain")


@admin.register(Page)
class PageAdmin(admin.ModelAdmin):
    list_display = ("title", "site", "path", "status", "is_homepage", "updated_at")
    list_filter = ("status", "is_homepage", "site")
    search_fields = ("title", "slug", "path")


@admin.register(PageRevision)
class PageRevisionAdmin(admin.ModelAdmin):
    list_display = ("page", "label", "created_at")
    list_filter = ("page__site",)
    search_fields = ("page__title", "label")


class PageExperimentVariantInline(admin.TabularInline):
    model = PageExperimentVariant
    extra = 0


class PageReviewCommentInline(admin.TabularInline):
    model = PageReviewComment
    extra = 0
    readonly_fields = ("author", "body", "mentions", "anchor", "is_resolved", "resolved_by", "resolved_at", "created_at")

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(PageExperiment)
class PageExperimentAdmin(admin.ModelAdmin):
    list_display = ("name", "site", "page", "locale", "status", "coverage_percent", "goal_form_name", "updated_at")
    list_filter = ("status", "site", "locale")
    search_fields = ("name", "key", "page__title", "site__name", "goal_form_name")
    inlines = [PageExperimentVariantInline]


@admin.register(ExperimentEvent)
class ExperimentEventAdmin(admin.ModelAdmin):
    list_display = ("experiment", "variant", "event_type", "visitor_id", "goal_key", "created_at")
    list_filter = ("event_type", "experiment__site")
    search_fields = ("experiment__name", "visitor_id", "goal_key", "request_path")


@admin.register(PageReview)
class PageReviewAdmin(admin.ModelAdmin):
    list_display = ("page", "locale", "status", "assigned_to", "requested_by", "approved_by", "updated_at")
    list_filter = ("status", "page__site", "locale")
    search_fields = ("page__title", "title", "last_note")
    inlines = [PageReviewCommentInline]


@admin.register(PageReviewComment)
class PageReviewCommentAdmin(admin.ModelAdmin):
    list_display = ("review", "author", "is_resolved", "resolved_by", "created_at")
    list_filter = ("is_resolved", "review__page__site")
    search_fields = ("body", "author__username", "review__page__title")


@admin.register(MediaAsset)
class MediaAssetAdmin(admin.ModelAdmin):
    list_display = ("title", "site", "kind", "created_at")
    list_filter = ("kind", "site")
    search_fields = ("title", "alt_text", "caption")


@admin.register(PostCategory)
class PostCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "site", "slug", "updated_at")
    list_filter = ("site",)
    search_fields = ("name", "slug")


@admin.register(PostTag)
class PostTagAdmin(admin.ModelAdmin):
    list_display = ("name", "site", "slug", "updated_at")
    list_filter = ("site",)
    search_fields = ("name", "slug")


@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    list_display = ("title", "site", "status", "published_at", "updated_at")
    list_filter = ("status", "site", "categories")
    search_fields = ("title", "slug", "excerpt")
    filter_horizontal = ("categories", "tags")


@admin.register(ProductCategory)
class ProductCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "site", "slug", "updated_at")
    list_filter = ("site",)
    search_fields = ("name", "slug")


class ProductVariantInline(admin.TabularInline):
    model = ProductVariant
    extra = 0


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("title", "site", "status", "is_featured", "published_at", "updated_at")
    list_filter = ("status", "is_featured", "site", "categories")
    search_fields = ("title", "slug", "excerpt")
    filter_horizontal = ("categories",)
    inlines = [ProductVariantInline]


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ("author_name", "post", "is_approved", "created_at")
    list_filter = ("is_approved", "post__site")
    search_fields = ("author_name", "author_email", "body", "post__title")


@admin.register(FormSubmission)
class FormSubmissionAdmin(admin.ModelAdmin):
    list_display = ("form_name", "site", "page", "status", "created_at")
    list_filter = ("status", "site")
    search_fields = ("form_name",)


class CartItemInline(admin.TabularInline):
    model = CartItem
    extra = 0
    readonly_fields = ("product_variant", "quantity", "unit_price", "line_total", "created_at", "updated_at")

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Cart)
class CartAdmin(admin.ModelAdmin):
    list_display = ("site", "session_key", "status", "subtotal", "total", "updated_at")
    list_filter = ("status", "site")
    search_fields = ("session_key",)
    inlines = [CartItemInline]


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ("title", "sku", "quantity", "unit_price", "line_total", "attributes")

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("order_number", "site", "customer_name", "status", "payment_status", "total", "placed_at")
    list_filter = ("status", "payment_status", "site")
    search_fields = ("order_number", "customer_name", "customer_email")
    readonly_fields = ("pricing_details",)
    inlines = [OrderItemInline]


class ShippingRateInline(admin.TabularInline):
    model = ShippingRate
    extra = 0


@admin.register(DiscountCode)
class DiscountCodeAdmin(admin.ModelAdmin):
    list_display = ("code", "site", "discount_type", "value", "min_purchase", "active", "use_count", "expires_at")
    list_filter = ("discount_type", "active", "site")
    search_fields = ("code", "site__name")


@admin.register(ShippingZone)
class ShippingZoneAdmin(admin.ModelAdmin):
    list_display = ("name", "site", "active", "created_at")
    list_filter = ("active", "site")
    search_fields = ("name", "site__name")
    inlines = [ShippingRateInline]


@admin.register(TaxRate)
class TaxRateAdmin(admin.ModelAdmin):
    list_display = ("name", "site", "rate", "active", "created_at")
    list_filter = ("active", "site")
    search_fields = ("name", "site__name")


@admin.register(BlockTemplate)
class BlockTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "site", "category", "is_global", "is_premium", "usage_count", "updated_at")
    list_filter = ("category", "is_global", "is_premium", "site")
    search_fields = ("name", "description")


@admin.register(URLRedirect)
class URLRedirectAdmin(admin.ModelAdmin):
    list_display = ("source_path", "target_path", "redirect_type", "status", "site", "hit_count", "updated_at")
    list_filter = ("redirect_type", "status", "site")
    search_fields = ("source_path", "target_path")


@admin.register(DomainContact)
class DomainContactAdmin(admin.ModelAdmin):
    list_display = ("first_name", "last_name", "email", "role", "site", "country", "updated_at")
    list_filter = ("role", "site", "country")
    search_fields = ("first_name", "last_name", "email", "organization")


@admin.register(Domain)
class DomainAdmin(admin.ModelAdmin):
    list_display = (
        "domain_name", "site", "is_primary", "status", "registration_status",
        "registrar", "expires_at", "ssl_enabled", "verified_at", "updated_at",
    )
    list_filter = ("status", "registration_status", "is_primary", "ssl_enabled", "registrar", "site")
    search_fields = ("domain_name", "registrar", "registrar_account")
    readonly_fields = ("verification_token", "verified_at", "last_verification_attempt", "whois_fetched_at")


@admin.register(DomainAvailability)
class DomainAvailabilityAdmin(admin.ModelAdmin):
    list_display = ("domain_name", "available", "price", "currency", "registrar", "checked_at")
    list_filter = ("available", "registrar")
    search_fields = ("domain_name",)


@admin.register(SEOAnalytics)
class SEOAnalyticsAdmin(admin.ModelAdmin):
    list_display = ("site", "page", "date", "impressions", "clicks", "ctr", "average_position", "source")
    list_filter = ("source", "site", "date")
    search_fields = ("site__name", "page__title")


@admin.register(MediaFolder)
class MediaFolderAdmin(admin.ModelAdmin):
    list_display = ("name", "site", "path", "parent", "updated_at")
    list_filter = ("site",)
    search_fields = ("name", "path")


@admin.register(NavigationMenu)
class NavigationMenuAdmin(admin.ModelAdmin):
    list_display = ("name", "site", "location", "slug", "is_active", "updated_at")
    list_filter = ("location", "is_active", "site")
    search_fields = ("name", "slug")


@admin.register(Webhook)
class WebhookAdmin(admin.ModelAdmin):
    list_display = ("name", "site", "event", "status", "success_count", "failure_count", "last_triggered_at")
    list_filter = ("event", "status", "site")
    search_fields = ("name", "url")


@admin.register(RobotsTxt)
class RobotsTxtAdmin(admin.ModelAdmin):
    list_display = ("site", "is_custom", "updated_at")
    list_filter = ("is_custom", "site")
    search_fields = ("site__name", "content")


@admin.register(PlatformSubscription)
class PlatformSubscriptionAdmin(admin.ModelAdmin):
    list_display = ("workspace", "plan", "status", "billing_cycle", "seats", "monthly_recurring_revenue", "updated_at")
    list_filter = ("plan", "status", "billing_cycle")
    search_fields = ("workspace__name", "workspace__owner__username", "workspace__owner__email")


@admin.register(PlatformOffer)
class PlatformOfferAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "offer_type", "target_plan", "status", "discount_value", "starts_at", "ends_at")
    list_filter = ("offer_type", "target_plan", "status")
    search_fields = ("name", "code", "headline")


@admin.register(PlatformEmailCampaign)
class PlatformEmailCampaignAdmin(admin.ModelAdmin):
    list_display = ("name", "audience_type", "status", "recipient_count", "sent_count", "sent_at", "updated_at")
    list_filter = ("audience_type", "status")
    search_fields = ("name", "subject", "preview_text")
