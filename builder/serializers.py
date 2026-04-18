from decimal import Decimal
import ipaddress
from urllib.parse import urlparse

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils.text import slugify
from rest_framework import serializers

from cms.page_schema import (
    PAGE_SCHEMA_VERSION,
    normalize_block_template_builder_data,
    normalize_block_template_renderer_key,
    normalize_page_content,
)

from .models import (
    BlockTemplate,
    Cart,
    CartItem,
    Comment,
    DiscountCode,
    Domain,
    DomainAvailability,
    DomainContact,
    EmailDomain,
    EmailProvisioningTask,
    MailAlias,
    Mailbox,
    ExperimentEvent,
    Form,
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
    PageTranslation,
    PageRevision,
    Post,
    PostCategory,
    PostTag,
    Product,
    ProductCategory,
    ProductVariant,
    ShippingRate,
    ShippingZone,
    KeywordRankEntry,
    SearchConsoleCredential,
    SEOAnalytics,
    SEOAudit,
    SEOSettings,
    Site,
    SiteLocale,
    TaxRate,
    TrackedKeyword,
    URLRedirect,
    Webhook,
    Workspace,
    WorkspaceInvitation,
    WorkspaceMembership,
)
from .experiments import normalize_experiment_key
from .localization import (
    build_translation_payload,
    clone_page_translation_content,
    ensure_site_locale,
    locale_direction,
    localized_preview_url,
    normalize_locale_code,
    normalize_translation_path,
    sync_site_localization_settings,
)
from .services import (
    create_site_starter_content,
    default_theme,
    ensure_site_commerce_modules,
    ensure_site_cms_modules,
    normalize_page_path,
    preview_url_for_page,
    preview_url_for_post,
    preview_url_for_product,
)


class PageRevisionSerializer(serializers.ModelSerializer):
    class Meta:
        model = PageRevision
        fields = ["id", "label", "builder_schema_version", "created_at"]


class PageTranslationSerializer(serializers.ModelSerializer):
    locale_code = serializers.CharField(source="locale.code", read_only=True)
    locale_direction = serializers.CharField(source="locale.direction", read_only=True)
    preview_url = serializers.SerializerMethodField()
    copy_source = serializers.BooleanField(write_only=True, required=False, default=True)

    class Meta:
        model = PageTranslation
        fields = [
            "id",
            "page",
            "locale",
            "locale_code",
            "locale_direction",
            "title",
            "slug",
            "path",
            "status",
            "seo",
            "page_settings",
            "builder_schema_version",
            "builder_data",
            "html",
            "css",
            "js",
            "published_at",
            "preview_url",
            "copy_source",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["path", "published_at"]
        extra_kwargs = {
            "title": {"required": False},
            "slug": {"required": False},
        }

    def get_preview_url(self, obj: PageTranslation) -> str:
        return localized_preview_url(
            obj.page.site.slug,
            obj.path,
            locale_code=obj.locale.code,
            is_homepage=obj.page.is_homepage,
        )

    def validate(self, attrs):
        page = attrs.get("page") or getattr(self.instance, "page", None)
        locale = attrs.get("locale") or getattr(self.instance, "locale", None)
        if not page or not locale:
            return attrs
        if locale.site_id != page.site_id:
            raise serializers.ValidationError({"locale": "Locale must belong to the same site as the page."})

        title = attrs.get("title") or getattr(self.instance, "title", None) or page.title
        slug = slugify(attrs.get("slug") or getattr(self.instance, "slug", None) or title) or "page"
        path = normalize_translation_path(slug, page.is_homepage)
        query = PageTranslation.objects.filter(locale=locale, path=path)
        if self.instance:
            query = query.exclude(pk=self.instance.pk)
        if query.exists():
            raise serializers.ValidationError({"slug": "Another translation already uses this path for the selected locale."})

        strict_schema_validation = any(
            field in attrs for field in ("builder_data", "seo", "page_settings", "builder_schema_version")
        )
        try:
            normalized_payload = normalize_page_content(
                title=attrs.get("title") or getattr(self.instance, "title", None) or page.title,
                slug=slug,
                path=path,
                is_homepage=page.is_homepage,
                status=attrs.get("status") or getattr(self.instance, "status", PageTranslation.STATUS_DRAFT),
                locale_code=locale.code,
                builder_data=attrs.get("builder_data", getattr(self.instance, "builder_data", {})),
                seo=attrs.get("seo", getattr(self.instance, "seo", {})),
                page_settings=attrs.get("page_settings", getattr(self.instance, "page_settings", {})),
                html=attrs.get("html", getattr(self.instance, "html", "")),
                css=attrs.get("css", getattr(self.instance, "css", "")),
                js=attrs.get("js", getattr(self.instance, "js", "")),
                schema_version=attrs.get(
                    "builder_schema_version",
                    getattr(self.instance, "builder_schema_version", PAGE_SCHEMA_VERSION),
                ),
                strict=strict_schema_validation,
            )
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict if hasattr(exc, "message_dict") else exc.messages) from exc
        attrs["slug"] = slug
        attrs["path"] = path
        attrs["builder_schema_version"] = normalized_payload["schema_version"]
        attrs["builder_data"] = normalized_payload["builder_data"]
        attrs["seo"] = normalized_payload["seo"]
        attrs["page_settings"] = normalized_payload["page_settings"]
        attrs["html"] = normalized_payload["html"]
        attrs["css"] = normalized_payload["css"]
        attrs["js"] = normalized_payload["js"]
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        copy_source = validated_data.pop("copy_source", True)
        page = validated_data["page"]
        locale = validated_data["locale"]
        if copy_source:
            translation, _ = clone_page_translation_content(page, locale)
            for field, value in validated_data.items():
                setattr(translation, field, value)
            translation.save()
            return translation
        return super().create(validated_data)

    @transaction.atomic
    def update(self, instance, validated_data):
        validated_data.pop("copy_source", None)
        return super().update(instance, validated_data)


class PageExperimentVariantSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(required=False)

    class Meta:
        model = PageExperimentVariant
        fields = [
            "id",
            "name",
            "key",
            "description",
            "is_control",
            "is_enabled",
            "weight",
            "title",
            "seo",
            "page_settings",
            "builder_data",
            "html",
            "css",
            "js",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]
        extra_kwargs = {
            "key": {"required": False, "allow_blank": True},
            "description": {"required": False, "allow_blank": True},
            "title": {"required": False, "allow_blank": True},
        }

    def validate(self, attrs):
        name = attrs.get("name") or getattr(self.instance, "name", "variant")
        attrs["key"] = slugify(attrs.get("key") or name) or "variant"
        weight = attrs.get("weight", getattr(self.instance, "weight", 1))
        if weight < 1:
            raise serializers.ValidationError({"weight": "Weight must be at least 1."})
        is_control = attrs.get("is_control", getattr(self.instance, "is_control", False))
        is_enabled = attrs.get("is_enabled", getattr(self.instance, "is_enabled", True))
        if is_control and not is_enabled:
            raise serializers.ValidationError({"is_enabled": "Control variants must remain enabled."})
        return attrs


class PageExperimentSerializer(serializers.ModelSerializer):
    locale_code = serializers.CharField(source="locale.code", read_only=True)
    variants = PageExperimentVariantSerializer(many=True)
    stats = serializers.SerializerMethodField()

    class Meta:
        model = PageExperiment
        fields = [
            "id",
            "site",
            "page",
            "locale",
            "locale_code",
            "name",
            "key",
            "hypothesis",
            "status",
            "coverage_percent",
            "goal_form_name",
            "audience",
            "starts_at",
            "ends_at",
            "settings",
            "variants",
            "stats",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at", "locale_code", "stats"]
        extra_kwargs = {
            "key": {"required": False, "allow_blank": True},
            "hypothesis": {"required": False, "allow_blank": True},
            "goal_form_name": {"required": False, "allow_blank": True},
        }

    def validate(self, attrs):
        site = attrs.get("site") or getattr(self.instance, "site", None)
        page = attrs.get("page") or getattr(self.instance, "page", None)
        locale = attrs.get("locale", getattr(self.instance, "locale", None))
        if not site or not page:
            return attrs
        if page.site_id != site.id:
            raise serializers.ValidationError({"page": "Selected page must belong to the selected site."})
        if locale and locale.site_id != site.id:
            raise serializers.ValidationError({"locale": "Selected locale must belong to the selected site."})

        attrs["key"] = normalize_experiment_key(attrs.get("key") or getattr(self.instance, "key", "") or attrs.get("name") or "")

        starts_at = attrs.get("starts_at", getattr(self.instance, "starts_at", None))
        ends_at = attrs.get("ends_at", getattr(self.instance, "ends_at", None))
        if starts_at and ends_at and starts_at >= ends_at:
            raise serializers.ValidationError({"ends_at": "End time must be after the start time."})

        variants = attrs.get("variants")
        if variants is not None:
            self._validate_variants(variants)
        elif not self.instance:
            raise serializers.ValidationError({"variants": "Create at least one control and one treatment variant."})

        next_status = attrs.get("status", getattr(self.instance, "status", PageExperiment.STATUS_DRAFT))
        if next_status == PageExperiment.STATUS_ACTIVE:
            conflict_query = PageExperiment.objects.filter(page=page, status=PageExperiment.STATUS_ACTIVE)
            conflict_query = conflict_query.filter(locale=locale) if locale else conflict_query.filter(locale__isnull=True)
            if self.instance:
                conflict_query = conflict_query.exclude(pk=self.instance.pk)
            if conflict_query.exists():
                scope = locale.code if locale else "the default locale"
                raise serializers.ValidationError(
                    {"status": f"Only one active experiment is allowed for {scope} on this page."}
                )
        return attrs

    def _validate_variants(self, variants):
        seen_keys: set[str] = set()
        enabled_variants = []
        control_count = 0
        for variant in variants:
            key = variant.get("key") or slugify(variant.get("name") or "variant") or "variant"
            if key in seen_keys:
                raise serializers.ValidationError({"variants": "Variant keys must be unique within an experiment."})
            seen_keys.add(key)
            if variant.get("is_enabled", True):
                enabled_variants.append(variant)
                if variant.get("is_control", False):
                    control_count += 1

        if len(enabled_variants) < 2:
            raise serializers.ValidationError({"variants": "Keep at least one control and one treatment variant enabled."})
        if control_count != 1:
            raise serializers.ValidationError({"variants": "Exactly one enabled control variant is required."})

    def _sync_variants(self, experiment: PageExperiment, variants_data):
        existing_map = {variant.id: variant for variant in experiment.variants.all()}
        for variant_data in variants_data:
            variant_id = variant_data.pop("id", None)
            variant_data["key"] = slugify(variant_data.get("key") or variant_data.get("name") or "variant") or "variant"
            if variant_id and variant_id in existing_map:
                variant = existing_map[variant_id]
                for field, value in variant_data.items():
                    setattr(variant, field, value)
                variant.save()
            else:
                PageExperimentVariant.objects.create(experiment=experiment, **variant_data)

    def create(self, validated_data):
        variants_data = validated_data.pop("variants")
        experiment = super().create(validated_data)
        self._sync_variants(experiment, variants_data)
        return experiment

    def update(self, instance, validated_data):
        variants_data = validated_data.pop("variants", None)
        experiment = super().update(instance, validated_data)
        if variants_data is not None:
            self._sync_variants(experiment, variants_data)
        return experiment

    def get_stats(self, obj: PageExperiment) -> dict[str, object]:
        variants = list(obj.variants.all())
        events = list(obj.events.all())
        exposures = [event for event in events if event.event_type == ExperimentEvent.EVENT_EXPOSURE]
        conversions = [event for event in events if event.event_type == ExperimentEvent.EVENT_CONVERSION]
        control_rate = 0.0
        variant_stats = []

        for variant in variants:
            variant_exposures = sum(1 for event in exposures if event.variant_id == variant.id)
            variant_conversions = sum(1 for event in conversions if event.variant_id == variant.id)
            conversion_rate = round((variant_conversions / variant_exposures) * 100, 2) if variant_exposures else 0.0
            stat = {
                "variant_id": variant.id,
                "variant_key": variant.key,
                "variant_name": variant.name,
                "is_control": variant.is_control,
                "is_enabled": variant.is_enabled,
                "exposures": variant_exposures,
                "conversions": variant_conversions,
                "conversion_rate": conversion_rate,
                "lift_percent": 0.0,
            }
            if variant.is_control:
                control_rate = conversion_rate
            variant_stats.append(stat)

        for stat in variant_stats:
            if stat["is_control"] or control_rate <= 0:
                continue
            stat["lift_percent"] = round(((stat["conversion_rate"] - control_rate) / control_rate) * 100, 2)

        winner = None
        ranked_variants = [item for item in variant_stats if item["exposures"] > 0]
        if ranked_variants:
            winner = max(ranked_variants, key=lambda item: (item["conversion_rate"], item["conversions"]))

        return {
            "exposures": len(exposures),
            "conversions": len(conversions),
            "conversion_rate": round((len(conversions) / len(exposures)) * 100, 2) if exposures else 0.0,
            "winner_variant_key": winner["variant_key"] if winner else "",
            "variant_stats": variant_stats,
        }


class CollaboratorUserSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    username = serializers.CharField()
    email = serializers.CharField(allow_blank=True)


class PageReviewCommentSerializer(serializers.ModelSerializer):
    author = CollaboratorUserSerializer(read_only=True)
    resolved_by_user = CollaboratorUserSerializer(source="resolved_by", read_only=True)
    parent_id = serializers.IntegerField(source="parent.id", read_only=True)

    class Meta:
        model = PageReviewComment
        fields = [
            "id",
            "review",
            "parent",
            "parent_id",
            "author",
            "body",
            "mentions",
            "anchor",
            "is_resolved",
            "resolved_by",
            "resolved_by_user",
            "resolved_at",
            "metadata",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "author",
            "resolved_by",
            "resolved_by_user",
            "resolved_at",
            "created_at",
            "updated_at",
        ]

    def validate(self, attrs):
        review = attrs.get("review") or getattr(self.instance, "review", None)
        parent = attrs.get("parent") or getattr(self.instance, "parent", None)
        if parent and review and parent.review_id != review.id:
            raise serializers.ValidationError({"parent": "Replies must belong to the same review thread."})
        return attrs


class PageReviewSerializer(serializers.ModelSerializer):
    locale_code = serializers.CharField(source="locale.code", read_only=True)
    requested_by_user = CollaboratorUserSerializer(source="requested_by", read_only=True)
    assigned_to_user = CollaboratorUserSerializer(source="assigned_to", read_only=True)
    approved_by_user = CollaboratorUserSerializer(source="approved_by", read_only=True)
    comments = PageReviewCommentSerializer(many=True, read_only=True)
    collaborators = serializers.SerializerMethodField()
    stats = serializers.SerializerMethodField()

    class Meta:
        model = PageReview
        fields = [
            "id",
            "page",
            "locale",
            "locale_code",
            "status",
            "title",
            "last_note",
            "requested_by",
            "requested_by_user",
            "assigned_to",
            "assigned_to_user",
            "approved_by",
            "approved_by_user",
            "requested_at",
            "responded_at",
            "approved_at",
            "metadata",
            "comments",
            "collaborators",
            "stats",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "requested_by",
            "locale_code",
            "requested_by_user",
            "assigned_to_user",
            "approved_by",
            "approved_by_user",
            "requested_at",
            "responded_at",
            "approved_at",
            "comments",
            "collaborators",
            "stats",
            "created_at",
            "updated_at",
        ]
        extra_kwargs = {
            "title": {"required": False, "allow_blank": True},
            "last_note": {"required": False, "allow_blank": True},
        }

    def validate(self, attrs):
        page = attrs.get("page") or getattr(self.instance, "page", None)
        locale = attrs.get("locale", getattr(self.instance, "locale", None))
        assigned_to = attrs.get("assigned_to", getattr(self.instance, "assigned_to", None))
        if not page:
            return attrs
        if locale and locale.site_id != page.site_id:
            raise serializers.ValidationError({"locale": "Locale must belong to the same site as the page."})
        if assigned_to and page.site.workspace_id:
            if not page.site.workspace.memberships.filter(user=assigned_to).exists():
                raise serializers.ValidationError({"assigned_to": "Assigned reviewer must be a workspace member."})
        return attrs

    def get_collaborators(self, obj: PageReview):
        site = obj.page.site
        workspace = site.workspace
        if not workspace:
            request = self.context.get("request")
            if request and request.user and request.user.is_authenticated:
                return CollaboratorUserSerializer([request.user], many=True).data
            return []
        cache = self.context.setdefault("_workspace_collaborator_cache", {})
        cache_key = workspace.id
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
        memberships = workspace.memberships.select_related("user").order_by("role", "user__username")
        payload = CollaboratorUserSerializer([membership.user for membership in memberships], many=True).data
        cache[cache_key] = payload
        return payload

    def get_stats(self, obj: PageReview) -> dict[str, object]:
        comments = list(obj.comments.all())
        open_comments = sum(1 for comment in comments if not comment.is_resolved)
        resolved_comments = sum(1 for comment in comments if comment.is_resolved)
        return {
            "comment_count": len(comments),
            "open_comment_count": open_comments,
            "resolved_comment_count": resolved_comments,
        }


class PageSerializer(serializers.ModelSerializer):
    revisions = PageRevisionSerializer(many=True, read_only=True)
    translations = PageTranslationSerializer(many=True, read_only=True)
    preview_url = serializers.SerializerMethodField()

    class Meta:
        model = Page
        fields = [
            "id",
            "site",
            "title",
            "slug",
            "path",
            "status",
            "is_homepage",
            "seo",
            "page_settings",
            "builder_schema_version",
            "builder_data",
            "html",
            "css",
            "js",
            "published_at",
            "scheduled_at",
            "preview_url",
            "revisions",
            "translations",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["path", "published_at"]

    def get_preview_url(self, obj: Page) -> str:
        return preview_url_for_page(obj)

    def validate(self, attrs):
        site = attrs.get("site") or getattr(self.instance, "site", None)
        title = attrs.get("title") or getattr(self.instance, "title", "page")
        requested_slug = attrs.get("slug")
        slug = slugify(requested_slug or title) or "page"
        is_homepage = attrs.get("is_homepage", getattr(self.instance, "is_homepage", False))
        path = normalize_page_path(slug, is_homepage)

        query = Page.objects.filter(site=site, path=path)
        if self.instance:
            query = query.exclude(pk=self.instance.pk)
        if query.exists():
            raise serializers.ValidationError({"slug": "Another page already uses this path."})

        strict_schema_validation = any(
            field in attrs for field in ("builder_data", "seo", "page_settings", "builder_schema_version")
        )
        try:
            normalized_payload = normalize_page_content(
                title=attrs.get("title") or getattr(self.instance, "title", None) or title,
                slug=slug,
                path=path,
                is_homepage=is_homepage,
                status=attrs.get("status") or getattr(self.instance, "status", Page.STATUS_DRAFT),
                locale_code="",
                builder_data=attrs.get("builder_data", getattr(self.instance, "builder_data", {})),
                seo=attrs.get("seo", getattr(self.instance, "seo", {})),
                page_settings=attrs.get("page_settings", getattr(self.instance, "page_settings", {})),
                html=attrs.get("html", getattr(self.instance, "html", "")),
                css=attrs.get("css", getattr(self.instance, "css", "")),
                js=attrs.get("js", getattr(self.instance, "js", "")),
                schema_version=attrs.get(
                    "builder_schema_version",
                    getattr(self.instance, "builder_schema_version", PAGE_SCHEMA_VERSION),
                ),
                strict=strict_schema_validation,
            )
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict if hasattr(exc, "message_dict") else exc.messages) from exc

        attrs["slug"] = slug
        attrs["path"] = path
        attrs["builder_schema_version"] = normalized_payload["schema_version"]
        attrs["builder_data"] = normalized_payload["builder_data"]
        attrs["seo"] = normalized_payload["seo"]
        attrs["page_settings"] = normalized_payload["page_settings"]
        attrs["html"] = normalized_payload["html"]
        attrs["css"] = normalized_payload["css"]
        attrs["js"] = normalized_payload["js"]
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        site = validated_data["site"]
        if not site.pages.exists():
            validated_data["is_homepage"] = True
            validated_data["path"] = "/"

        page = super().create(validated_data)
        if page.is_homepage:
            Page.objects.filter(site=site, is_homepage=True).exclude(pk=page.pk).update(is_homepage=False)
        return page

    @transaction.atomic
    def update(self, instance, validated_data):
        page = super().update(instance, validated_data)
        if page.is_homepage:
            Page.objects.filter(site=page.site, is_homepage=True).exclude(pk=page.pk).update(is_homepage=False)
        elif not page.site.pages.filter(is_homepage=True).exists():
            page.is_homepage = True
            page.path = "/"
            page.save(update_fields=["is_homepage", "path"])
        return page


class SiteLocaleSerializer(serializers.ModelSerializer):
    class Meta:
        model = SiteLocale
        fields = [
            "id",
            "site",
            "code",
            "direction",
            "is_default",
            "is_enabled",
            "created_at",
            "updated_at",
        ]

    def validate(self, attrs):
        site = attrs.get("site") or getattr(self.instance, "site", None)
        code = attrs.get("code") or getattr(self.instance, "code", "")
        normalized_code = normalize_locale_code(code)
        attrs["code"] = normalized_code
        attrs["direction"] = locale_direction(normalized_code)

        next_is_default = attrs.get("is_default", getattr(self.instance, "is_default", False))
        next_is_enabled = attrs.get("is_enabled", getattr(self.instance, "is_enabled", True))
        if next_is_default and not next_is_enabled:
            raise serializers.ValidationError({"is_enabled": "Default locale must remain enabled."})

        query = SiteLocale.objects.filter(site=site, code=normalized_code)
        if self.instance:
            query = query.exclude(pk=self.instance.pk)
        if query.exists():
            raise serializers.ValidationError({"code": "This locale already exists for the selected site."})
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        make_default = validated_data.get("is_default", False)
        locale = super().create(validated_data)
        if make_default:
            locale.site.locales.exclude(pk=locale.pk).update(is_default=False)
        sync_site_localization_settings(locale.site)
        return locale

    @transaction.atomic
    def update(self, instance, validated_data):
        make_default = validated_data.get("is_default", instance.is_default)
        locale = super().update(instance, validated_data)
        if make_default and locale.is_enabled:
            locale.site.locales.exclude(pk=locale.pk).update(is_default=False)
            if not locale.is_default:
                locale.is_default = True
                locale.save(update_fields=["is_default", "updated_at"])
        elif locale.is_default and not locale.is_enabled:
            replacement = locale.site.locales.exclude(pk=locale.pk).filter(is_enabled=True).order_by("code").first()
            locale.is_default = False
            locale.save(update_fields=["is_default", "updated_at"])
            if replacement:
                replacement.is_default = True
                replacement.save(update_fields=["is_default", "updated_at"])
        elif not locale.site.locales.exclude(pk=locale.pk).filter(is_default=True).exists() and locale.is_enabled:
            locale.is_default = True
            locale.save(update_fields=["is_default", "updated_at"])
        sync_site_localization_settings(locale.site)
        return locale


class SiteSerializer(serializers.ModelSerializer):
    pages = PageSerializer(many=True, read_only=True)
    locales = SiteLocaleSerializer(many=True, read_only=True)
    starter_kit = serializers.CharField(write_only=True, required=False, allow_blank=True)

    class Meta:
        model = Site
        fields = [
            "id",
            "name",
            "slug",
            "tagline",
            "domain",
            "description",
            "theme",
            "navigation",
            "settings",
            "locales",
            "starter_kit",
            "pages",
            "created_at",
            "updated_at",
        ]

    def validate(self, attrs):
        name = attrs.get("name") or getattr(self.instance, "name", "site")
        current_theme = getattr(self.instance, "theme", {})
        slug_value = attrs.get("slug") or getattr(self.instance, "slug", "") or name
        attrs["slug"] = slugify(slug_value) or "site"
        attrs["theme"] = {**default_theme(), **current_theme, **(attrs.get("theme") or {})}
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        starter_kit = validated_data.pop("starter_kit", "") or "agency"
        site = super().create(validated_data)
        localization_settings = site.settings.get("localization") if isinstance(site.settings, dict) else {}
        default_locale_code = (localization_settings or {}).get("default_locale") or "en"
        ensure_site_locale(site, default_locale_code, is_default=True)
        create_site_starter_content(site, starter_kit)
        ensure_site_cms_modules(site)
        ensure_site_commerce_modules(site)
        return site


class BuilderSaveSerializer(serializers.Serializer):
    title = serializers.CharField(required=False, max_length=180)
    slug = serializers.CharField(required=False, allow_blank=True, max_length=180)
    is_homepage = serializers.BooleanField(required=False)
    seo = serializers.JSONField(required=False)
    page_settings = serializers.JSONField(required=False)
    builder_schema_version = serializers.IntegerField(required=False, min_value=1)
    builder_data = serializers.JSONField(required=False)
    project_data = serializers.JSONField(required=False)
    html = serializers.CharField(required=False, allow_blank=True)
    css = serializers.CharField(required=False, allow_blank=True)
    js = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        has_builder_payload = "builder_data" in attrs or "project_data" in attrs
        builder_data = attrs.get("builder_data")
        project_data = attrs.get("project_data")
        if builder_data is not None and project_data is not None and builder_data != project_data:
            raise serializers.ValidationError(
                {"builder_data": "Provide either builder_data or project_data; do not send conflicting values."}
            )

        canonical_builder_data = builder_data if builder_data is not None else project_data
        if canonical_builder_data is None:
            canonical_builder_data = {}

        seo = attrs.get("seo", {})
        page_settings = attrs.get("page_settings", {})
        title = attrs.get("title") or "Page"
        slug = slugify(attrs.get("slug") or title) or "page"
        path = normalize_page_path(slug, attrs.get("is_homepage", False))

        try:
            normalized_payload = normalize_page_content(
                title=title,
                slug=slug,
                path=path,
                is_homepage=attrs.get("is_homepage", False),
                status=Page.STATUS_DRAFT,
                locale_code="",
                builder_data=canonical_builder_data,
                seo=seo,
                page_settings=page_settings,
                html=attrs.get("html", ""),
                css=attrs.get("css", ""),
                js=attrs.get("js", ""),
                schema_version=attrs.get("builder_schema_version", PAGE_SCHEMA_VERSION),
                strict=True,
            )
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict if hasattr(exc, "message_dict") else exc.messages) from exc

        attrs["builder_schema_version"] = normalized_payload["schema_version"]
        if has_builder_payload:
            attrs["builder_data"] = normalized_payload["builder_data"]
            attrs["project_data"] = normalized_payload["builder_data"]
        if "seo" in attrs:
            attrs["seo"] = normalized_payload["seo"]
        if "page_settings" in attrs:
            attrs["page_settings"] = normalized_payload["page_settings"]
        if "html" in attrs:
            attrs["html"] = normalized_payload["html"]
        if "css" in attrs:
            attrs["css"] = normalized_payload["css"]
        if "js" in attrs:
            attrs["js"] = normalized_payload["js"]
        return attrs


class SiteMirrorImportSerializer(serializers.Serializer):
    source_path = serializers.CharField(max_length=500)
    publish = serializers.BooleanField(required=False, default=True)
    replace_existing = serializers.BooleanField(required=False, default=True)


class MediaAssetSerializer(serializers.ModelSerializer):
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = MediaAsset
        fields = [
            "id",
            "site",
            "title",
            "file",
            "file_url",
            "alt_text",
            "caption",
            "kind",
            "metadata",
            "created_at",
            "updated_at",
        ]

    def get_file_url(self, obj: MediaAsset) -> str:
        if not obj.file:
            return ""
        request = self.context.get("request")
        if request:
            return request.build_absolute_uri(obj.file.url)
        return obj.file.url

    def validate(self, attrs):
        title = attrs.get("title") or getattr(self.instance, "title", "")
        uploaded_file = attrs.get("file") or getattr(self.instance, "file", None)
        if not title and uploaded_file:
            attrs["title"] = uploaded_file.name.rsplit("/", 1)[-1]
        return attrs


class PostCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = PostCategory
        fields = ["id", "site", "name", "slug", "description", "created_at", "updated_at"]

    def validate(self, attrs):
        site = attrs.get("site") or getattr(self.instance, "site", None)
        name = attrs.get("name") or getattr(self.instance, "name", "category")
        attrs["slug"] = slugify(attrs.get("slug") or name) or "category"
        query = PostCategory.objects.filter(site=site, slug=attrs["slug"])
        if self.instance:
            query = query.exclude(pk=self.instance.pk)
        if query.exists():
            raise serializers.ValidationError({"slug": "Another category already uses this slug."})
        return attrs


class PostTagSerializer(serializers.ModelSerializer):
    class Meta:
        model = PostTag
        fields = ["id", "site", "name", "slug", "created_at", "updated_at"]

    def validate(self, attrs):
        site = attrs.get("site") or getattr(self.instance, "site", None)
        name = attrs.get("name") or getattr(self.instance, "name", "tag")
        attrs["slug"] = slugify(attrs.get("slug") or name) or "tag"
        query = PostTag.objects.filter(site=site, slug=attrs["slug"])
        if self.instance:
            query = query.exclude(pk=self.instance.pk)
        if query.exists():
            raise serializers.ValidationError({"slug": "Another tag already uses this slug."})
        return attrs


class ProductCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductCategory
        fields = ["id", "site", "name", "slug", "description", "created_at", "updated_at"]

    def validate(self, attrs):
        site = attrs.get("site") or getattr(self.instance, "site", None)
        name = attrs.get("name") or getattr(self.instance, "name", "category")
        attrs["slug"] = slugify(attrs.get("slug") or name) or "category"
        query = ProductCategory.objects.filter(site=site, slug=attrs["slug"])
        if self.instance:
            query = query.exclude(pk=self.instance.pk)
        if query.exists():
            raise serializers.ValidationError({"slug": "Another product category already uses this slug."})
        return attrs


class DiscountCodeSerializer(serializers.ModelSerializer):
    class Meta:
        model = DiscountCode
        fields = [
            "id",
            "site",
            "code",
            "discount_type",
            "value",
            "min_purchase",
            "max_uses",
            "use_count",
            "active",
            "starts_at",
            "expires_at",
            "created_at",
        ]
        read_only_fields = ["use_count", "created_at"]

    def validate(self, attrs):
        site = attrs.get("site") or getattr(self.instance, "site", None)
        code = (attrs.get("code") or getattr(self.instance, "code", "")).strip().upper()
        if not code:
            raise serializers.ValidationError({"code": "Code is required."})
        attrs["code"] = code

        query = DiscountCode.objects.filter(site=site, code__iexact=code)
        if self.instance:
            query = query.exclude(pk=self.instance.pk)
        if query.exists():
            raise serializers.ValidationError({"code": "Another discount already uses this code."})

        value = attrs.get("value", getattr(self.instance, "value", Decimal("0.00")))
        discount_type = attrs.get("discount_type", getattr(self.instance, "discount_type", DiscountCode.TYPE_FIXED))
        if value < 0:
            raise serializers.ValidationError({"value": "Discount value cannot be negative."})
        if discount_type == DiscountCode.TYPE_PERCENTAGE and value > 100:
            raise serializers.ValidationError({"value": "Percentage discounts must be 100 or less."})
        return attrs


class ShippingRateSerializer(serializers.ModelSerializer):
    zone_name = serializers.CharField(source="zone.name", read_only=True)

    class Meta:
        model = ShippingRate
        fields = [
            "id",
            "zone",
            "zone_name",
            "name",
            "method_code",
            "price",
            "estimated_days_min",
            "estimated_days_max",
            "active",
        ]

    def validate(self, attrs):
        zone = attrs.get("zone") or getattr(self.instance, "zone", None)
        method_code = slugify(attrs.get("method_code") or getattr(self.instance, "method_code", "") or attrs.get("name") or "shipping")
        attrs["method_code"] = method_code
        query = ShippingRate.objects.filter(zone=zone, method_code=method_code)
        if self.instance:
            query = query.exclude(pk=self.instance.pk)
        if query.exists():
            raise serializers.ValidationError({"method_code": "Another rate already uses this method code in the selected zone."})

        if attrs.get("estimated_days_min", getattr(self.instance, "estimated_days_min", 0)) > attrs.get(
            "estimated_days_max",
            getattr(self.instance, "estimated_days_max", 0),
        ):
            raise serializers.ValidationError({"estimated_days_max": "Maximum delivery days must be greater than or equal to minimum delivery days."})
        return attrs


class ShippingZoneSerializer(serializers.ModelSerializer):
    rates = ShippingRateSerializer(many=True, read_only=True)

    class Meta:
        model = ShippingZone
        fields = ["id", "site", "name", "countries", "active", "created_at", "rates"]
        read_only_fields = ["created_at"]

    def validate(self, attrs):
        site = attrs.get("site") or getattr(self.instance, "site", None)
        name = (attrs.get("name") or getattr(self.instance, "name", "")).strip()
        if not name:
            raise serializers.ValidationError({"name": "Zone name is required."})

        query = ShippingZone.objects.filter(site=site, name__iexact=name)
        if self.instance:
            query = query.exclude(pk=self.instance.pk)
        if query.exists():
            raise serializers.ValidationError({"name": "Another shipping zone already uses this name."})

        countries = attrs.get("countries", getattr(self.instance, "countries", []))
        normalized_countries = []
        for country in countries:
            value = str(country).strip().upper()
            if value:
                normalized_countries.append(value)
        if not normalized_countries:
            raise serializers.ValidationError({"countries": "Provide at least one country code or '*' wildcard."})
        attrs["countries"] = normalized_countries
        return attrs


class TaxRateSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaxRate
        fields = ["id", "site", "name", "rate", "countries", "states", "active", "created_at"]
        read_only_fields = ["created_at"]

    def validate(self, attrs):
        site = attrs.get("site") or getattr(self.instance, "site", None)
        name = (attrs.get("name") or getattr(self.instance, "name", "")).strip()
        if not name:
            raise serializers.ValidationError({"name": "Tax rate name is required."})

        query = TaxRate.objects.filter(site=site, name__iexact=name)
        if self.instance:
            query = query.exclude(pk=self.instance.pk)
        if query.exists():
            raise serializers.ValidationError({"name": "Another tax rate already uses this name."})

        rate = attrs.get("rate", getattr(self.instance, "rate", Decimal("0.00")))
        if rate < 0 or rate > 1:
            raise serializers.ValidationError({"rate": "Tax rate must be between 0 and 1."})

        countries = [str(code).strip().upper() for code in attrs.get("countries", getattr(self.instance, "countries", [])) if str(code).strip()]
        if not countries:
            raise serializers.ValidationError({"countries": "Provide at least one country code."})
        attrs["countries"] = countries
        attrs["states"] = [
            str(code).strip().upper()
            for code in attrs.get("states", getattr(self.instance, "states", []))
            if str(code).strip()
        ]
        return attrs


class FormSerializer(serializers.ModelSerializer):
    """Serializer for form builder forms."""
    submission_count = serializers.SerializerMethodField()

    class Meta:
        model = Form
        fields = [
            "id",
            "site",
            "name",
            "slug",
            "description",
            "status",
            "fields",
            "submit_button_text",
            "success_message",
            "redirect_url",
            "notify_emails",
            "enable_captcha",
            "honeypot_field",
            "form_class",
            "settings",
            "submission_count",
            "created_at",
            "updated_at",
        ]

    def get_submission_count(self, obj) -> int:
        annotated_count = getattr(obj, "submission_count_annotated", None)
        if annotated_count is not None:
            return int(annotated_count)
        return FormSubmission.objects.filter(site=obj.site, form_name=obj.slug).count()

    def validate(self, attrs):
        site = attrs.get("site") or getattr(self.instance, "site", None)
        name = attrs.get("name") or getattr(self.instance, "name", "form")
        attrs["slug"] = slugify(attrs.get("slug") or name) or "form"
        query = Form.objects.filter(site=site, slug=attrs["slug"])
        if self.instance:
            query = query.exclude(pk=self.instance.pk)
        if query.exists():
            raise serializers.ValidationError({"slug": "Another form already uses this slug."})
        return attrs


class FormFieldSerializer(serializers.Serializer):
    """Serializer for individual form fields."""
    id = serializers.CharField()
    type = serializers.ChoiceField(choices=[
        "text", "email", "tel", "number", "textarea", "select", "radio", "checkbox", "date", "time", "file", "hidden"
    ])
    label = serializers.CharField(max_length=140)
    name = serializers.CharField(max_length=60)
    placeholder = serializers.CharField(max_length=255, required=False, allow_blank=True)
    required = serializers.BooleanField(default=False)
    options = serializers.ListField(child=serializers.CharField(), required=False)
    validation = serializers.DictField(required=False)
    default_value = serializers.CharField(required=False, allow_blank=True)
    help_text = serializers.CharField(max_length=255, required=False, allow_blank=True)


class ProductVariantSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductVariant
        fields = [
            "id",
            "product",
            "title",
            "sku",
            "price",
            "compare_at_price",
            "inventory",
            "track_inventory",
            "is_default",
            "is_active",
            "attributes",
            "created_at",
            "updated_at",
        ]

    def validate(self, attrs):
        product = attrs.get("product") or getattr(self.instance, "product", None)
        title = attrs.get("title") or getattr(self.instance, "title", "variant")
        sku = (attrs.get("sku") or getattr(self.instance, "sku", "") or slugify(title) or "variant").upper()
        attrs["sku"] = sku

        query = ProductVariant.objects.filter(product=product, sku=sku)
        if self.instance:
            query = query.exclude(pk=self.instance.pk)
        if query.exists():
            raise serializers.ValidationError({"sku": "Another variant already uses this SKU."})

        price = attrs.get("price", getattr(self.instance, "price", None))
        compare_at_price = attrs.get("compare_at_price", getattr(self.instance, "compare_at_price", None))
        if compare_at_price is not None and price is not None and compare_at_price < price:
            raise serializers.ValidationError({"compare_at_price": "Compare-at price must be greater than or equal to price."})

        inventory = attrs.get("inventory", getattr(self.instance, "inventory", 0))
        if inventory < 0:
            raise serializers.ValidationError({"inventory": "Inventory cannot be negative."})

        return attrs

    @transaction.atomic
    def create(self, validated_data):
        product = validated_data["product"]
        if not product.variants.exists():
            validated_data["is_default"] = True

        variant = super().create(validated_data)
        if variant.is_default:
            product.variants.exclude(pk=variant.pk).update(is_default=False)
        return variant

    @transaction.atomic
    def update(self, instance, validated_data):
        variant = super().update(instance, validated_data)
        if variant.is_default:
            variant.product.variants.exclude(pk=variant.pk).update(is_default=False)
        elif not variant.product.variants.exclude(pk=variant.pk).filter(is_default=True, is_active=True).exists():
            variant.is_default = True
            variant.save(update_fields=["is_default", "updated_at"])
        return variant


class CommentSerializer(serializers.ModelSerializer):
    post_title = serializers.CharField(source="post.title", read_only=True)

    class Meta:
        model = Comment
        fields = [
            "id",
            "post",
            "post_title",
            "author_name",
            "author_email",
            "body",
            "is_approved",
            "created_at",
            "updated_at",
        ]


class PostSerializer(serializers.ModelSerializer):
    categories = PostCategorySerializer(many=True, read_only=True)
    tags = PostTagSerializer(many=True, read_only=True)
    category_ids = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=PostCategory.objects.all(),
        source="categories",
        required=False,
        write_only=True,
    )
    tag_ids = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=PostTag.objects.all(),
        source="tags",
        required=False,
        write_only=True,
    )
    featured_media_url = serializers.SerializerMethodField()
    preview_url = serializers.SerializerMethodField()
    comments = CommentSerializer(many=True, read_only=True)

    class Meta:
        model = Post
        fields = [
            "id",
            "site",
            "title",
            "slug",
            "excerpt",
            "body_html",
            "status",
            "featured_media",
            "featured_media_url",
            "categories",
            "tags",
            "category_ids",
            "tag_ids",
            "seo",
            "published_at",
            "scheduled_at",
            "preview_url",
            "comments",
            "created_at",
            "updated_at",
        ]

    def get_featured_media_url(self, obj: Post) -> str:
        if not obj.featured_media or not obj.featured_media.file:
            return ""
        request = self.context.get("request")
        if request:
            return request.build_absolute_uri(obj.featured_media.file.url)
        return obj.featured_media.file.url

    def get_preview_url(self, obj: Post) -> str:
        return preview_url_for_post(obj)

    def validate(self, attrs):
        site = attrs.get("site") or getattr(self.instance, "site", None)
        title = attrs.get("title") or getattr(self.instance, "title", "post")
        attrs["slug"] = slugify(attrs.get("slug") or title) or "post"

        query = Post.objects.filter(site=site, slug=attrs["slug"])
        if self.instance:
            query = query.exclude(pk=self.instance.pk)
        if query.exists():
            raise serializers.ValidationError({"slug": "Another post already uses this slug."})

        featured_media = attrs.get("featured_media") or getattr(self.instance, "featured_media", None)
        if featured_media and featured_media.site_id != site.id:
            raise serializers.ValidationError({"featured_media": "Featured media must belong to the same site."})

        for category in attrs.get("categories", []):
            if category.site_id != site.id:
                raise serializers.ValidationError({"category_ids": "Categories must belong to the same site."})
        for tag in attrs.get("tags", []):
            if tag.site_id != site.id:
                raise serializers.ValidationError({"tag_ids": "Tags must belong to the same site."})

        return attrs

    @transaction.atomic
    def create(self, validated_data):
        categories = validated_data.pop("categories", [])
        tags = validated_data.pop("tags", [])
        post = super().create(validated_data)
        if categories:
            post.categories.set(categories)
        if tags:
            post.tags.set(tags)
        return post

    @transaction.atomic
    def update(self, instance, validated_data):
        categories = validated_data.pop("categories", None)
        tags = validated_data.pop("tags", None)
        post = super().update(instance, validated_data)
        if categories is not None:
            post.categories.set(categories)
        if tags is not None:
            post.tags.set(tags)
        return post


class ProductSerializer(serializers.ModelSerializer):
    categories = ProductCategorySerializer(many=True, read_only=True)
    category_ids = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=ProductCategory.objects.all(),
        source="categories",
        required=False,
        write_only=True,
    )
    featured_media_url = serializers.SerializerMethodField()
    preview_url = serializers.SerializerMethodField()
    variants = ProductVariantSerializer(many=True, read_only=True)

    class Meta:
        model = Product
        fields = [
            "id",
            "site",
            "title",
            "slug",
            "excerpt",
            "description_html",
            "status",
            "featured_media",
            "featured_media_url",
            "categories",
            "category_ids",
            "seo",
            "settings",
            "is_featured",
            "published_at",
            "preview_url",
            "variants",
            "created_at",
            "updated_at",
        ]

    def get_featured_media_url(self, obj: Product) -> str:
        if not obj.featured_media or not obj.featured_media.file:
            return ""
        request = self.context.get("request")
        if request:
            return request.build_absolute_uri(obj.featured_media.file.url)
        return obj.featured_media.file.url

    def get_preview_url(self, obj: Product) -> str:
        return preview_url_for_product(obj)

    def validate(self, attrs):
        site = attrs.get("site") or getattr(self.instance, "site", None)
        title = attrs.get("title") or getattr(self.instance, "title", "product")
        attrs["slug"] = slugify(attrs.get("slug") or title) or "product"

        query = Product.objects.filter(site=site, slug=attrs["slug"])
        if self.instance:
            query = query.exclude(pk=self.instance.pk)
        if query.exists():
            raise serializers.ValidationError({"slug": "Another product already uses this slug."})

        featured_media = attrs.get("featured_media") or getattr(self.instance, "featured_media", None)
        if featured_media and site and featured_media.site_id != site.id:
            raise serializers.ValidationError({"featured_media": "Featured media must belong to the same site."})

        for category in attrs.get("categories", []):
            if site and category.site_id != site.id:
                raise serializers.ValidationError({"category_ids": "Categories must belong to the same site."})

        return attrs

    @transaction.atomic
    def create(self, validated_data):
        categories = validated_data.pop("categories", [])
        product = super().create(validated_data)
        if categories:
            product.categories.set(categories)
        return product

    @transaction.atomic
    def update(self, instance, validated_data):
        categories = validated_data.pop("categories", None)
        product = super().update(instance, validated_data)
        if categories is not None:
            product.categories.set(categories)
        return product


class FormSubmissionSerializer(serializers.ModelSerializer):
    page_title = serializers.CharField(source="page.title", read_only=True)

    class Meta:
        model = FormSubmission
        fields = [
            "id",
            "site",
            "page",
            "page_title",
            "form_name",
            "payload",
            "status",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at", "page_title"]

    def validate(self, attrs):
        site = attrs.get("site") or getattr(self.instance, "site", None)
        page = attrs.get("page") or getattr(self.instance, "page", None)
        if self.instance:
            immutable_changes = {}
            if "site" in attrs:
                new_site_id = attrs["site"].pk if attrs["site"] is not None else None
                if new_site_id != self.instance.site_id:
                    immutable_changes["site"] = "This field cannot be modified after creation."
            if "page" in attrs:
                new_page_id = attrs["page"].pk if attrs["page"] is not None else None
                if new_page_id != self.instance.page_id:
                    immutable_changes["page"] = "This field cannot be modified after creation."
            if "form_name" in attrs and attrs["form_name"] != self.instance.form_name:
                immutable_changes["form_name"] = "This field cannot be modified after creation."
            if "payload" in attrs and attrs["payload"] != self.instance.payload:
                immutable_changes["payload"] = "This field cannot be modified after creation."
            if immutable_changes:
                raise serializers.ValidationError(immutable_changes)
        if not site:
            raise serializers.ValidationError({"site": "Site is required."})
        if page and page.site_id != site.id:
            raise serializers.ValidationError({"page": "Selected page must belong to the same site."})
        return attrs


class CartItemSerializer(serializers.ModelSerializer):
    product_id = serializers.IntegerField(source="product_variant.product_id", read_only=True)
    product_title = serializers.CharField(source="product_variant.product.title", read_only=True)
    product_slug = serializers.CharField(source="product_variant.product.slug", read_only=True)
    product_preview_url = serializers.SerializerMethodField()
    variant_title = serializers.CharField(source="product_variant.title", read_only=True)
    sku = serializers.CharField(source="product_variant.sku", read_only=True)
    attributes = serializers.JSONField(source="product_variant.attributes", read_only=True)

    class Meta:
        model = CartItem
        fields = [
            "id",
            "product_variant",
            "product_id",
            "product_title",
            "product_slug",
            "product_preview_url",
            "variant_title",
            "sku",
            "attributes",
            "quantity",
            "unit_price",
            "line_total",
            "created_at",
            "updated_at",
        ]

    def get_product_preview_url(self, obj: CartItem) -> str:
        return preview_url_for_product(obj.product_variant.product)


class CartSerializer(serializers.ModelSerializer):
    items = CartItemSerializer(many=True, read_only=True)
    item_count = serializers.SerializerMethodField()

    class Meta:
        model = Cart
        fields = [
            "id",
            "site",
            "currency",
            "subtotal",
            "total",
            "status",
            "item_count",
            "items",
            "created_at",
            "updated_at",
        ]

    def get_item_count(self, obj: Cart) -> int:
        return sum(item.quantity for item in obj.items.all())


class OrderItemSerializer(serializers.ModelSerializer):
    product_preview_url = serializers.SerializerMethodField()

    class Meta:
        model = OrderItem
        fields = [
            "id",
            "product",
            "product_variant",
            "title",
            "sku",
            "quantity",
            "unit_price",
            "line_total",
            "attributes",
            "product_preview_url",
        ]

    def get_product_preview_url(self, obj: OrderItem) -> str:
        if not obj.product:
            return ""
        return preview_url_for_product(obj.product)


class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)

    class Meta:
        model = Order
        fields = [
            "id",
            "site",
            "order_number",
            "status",
            "payment_status",
            "currency",
            "customer_name",
            "customer_email",
            "customer_phone",
            "billing_address",
            "shipping_address",
            "notes",
            "subtotal",
            "shipping_total",
            "tax_total",
            "discount_total",
            "total",
            "pricing_details",
            "payment_provider",
            "payment_reference",
            "placed_at",
            "items",
            "created_at",
            "updated_at",
        ]


class PublicCartAddSerializer(serializers.Serializer):
    product_slug = serializers.SlugField(max_length=180)
    variant_id = serializers.IntegerField(required=False, min_value=1)
    quantity = serializers.IntegerField(required=False, min_value=1, default=1)


class PublicCartItemUpdateSerializer(serializers.Serializer):
    quantity = serializers.IntegerField(min_value=0)


class PublicCheckoutSerializer(serializers.Serializer):
    customer_name = serializers.CharField(max_length=180)
    customer_email = serializers.EmailField()
    customer_phone = serializers.CharField(required=False, allow_blank=True, max_length=40)
    billing_address = serializers.JSONField(required=False)
    shipping_address = serializers.JSONField(required=False)
    shipping_rate_id = serializers.IntegerField(required=False, min_value=1)
    discount_code = serializers.CharField(required=False, allow_blank=True, max_length=50)
    notes = serializers.CharField(required=False, allow_blank=True)


class PublicCartPricingSerializer(serializers.Serializer):
    shipping_address = serializers.JSONField(required=False)
    shipping_rate_id = serializers.IntegerField(required=False, min_value=1)
    discount_code = serializers.CharField(required=False, allow_blank=True, max_length=50)


class PaymentIntentSerializer(serializers.Serializer):
    """Serializer for creating a payment intent."""
    order_id = serializers.IntegerField()


class PaymentIntentResponseSerializer(serializers.Serializer):
    """Response serializer for payment intent creation."""
    client_secret = serializers.CharField()
    payment_intent_id = serializers.CharField()
    amount = serializers.IntegerField()
    currency = serializers.CharField()
    publishable_key = serializers.CharField()


class PaymentConfigSerializer(serializers.Serializer):
    """Serializer for payment configuration status."""
    stripe_configured = serializers.BooleanField()
    publishable_key = serializers.CharField(allow_blank=True)
    default_provider = serializers.CharField()


class AuthBootstrapSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    email = serializers.EmailField(required=False, allow_blank=True)
    password = serializers.CharField(min_length=8, max_length=128, write_only=True)


class AuthLoginSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(max_length=128, write_only=True)


class PublicFormSubmissionSerializer(serializers.Serializer):
    site_slug = serializers.SlugField(max_length=160)
    page_path = serializers.CharField(required=False, allow_blank=True, max_length=255)
    form_name = serializers.CharField(max_length=140)
    payload = serializers.JSONField()


class PublicCommentSubmissionSerializer(serializers.Serializer):
    site_slug = serializers.SlugField(max_length=160)
    post_slug = serializers.SlugField(max_length=180)
    author_name = serializers.CharField(max_length=140)
    author_email = serializers.EmailField()
    body = serializers.CharField(max_length=5000)

    def validate_body(self, value: str) -> str:
        normalized = (value or "").strip()
        if not normalized:
            raise serializers.ValidationError("Comment body cannot be empty.")
        return normalized


class SiteBlueprintSectionSerializer(serializers.Serializer):
    id = serializers.CharField(required=False, allow_blank=True, max_length=80)
    kind = serializers.CharField(max_length=40)
    title = serializers.CharField(max_length=140)
    summary = serializers.CharField(required=False, allow_blank=True, max_length=280)


class SiteBlueprintSEOItemSerializer(serializers.Serializer):
    meta_title = serializers.CharField(required=False, allow_blank=True, max_length=60)
    meta_description = serializers.CharField(required=False, allow_blank=True, max_length=155)
    focus_keywords = serializers.ListField(
        child=serializers.CharField(max_length=80),
        required=False,
        allow_empty=True,
    )


class SiteBlueprintPageSerializer(serializers.Serializer):
    id = serializers.CharField(required=False, allow_blank=True, max_length=80)
    title = serializers.CharField(max_length=180)
    slug = serializers.CharField(required=False, allow_blank=True, max_length=180)
    path = serializers.CharField(required=False, allow_blank=True, max_length=255)
    purpose = serializers.CharField(required=False, allow_blank=True, max_length=280)
    is_homepage = serializers.BooleanField(required=False, default=False)
    parent_id = serializers.CharField(required=False, allow_blank=True, max_length=80)
    sections = SiteBlueprintSectionSerializer(many=True, required=False)
    seo = SiteBlueprintSEOItemSerializer(required=False)


class SiteBlueprintPayloadSerializer(serializers.Serializer):
    site_name = serializers.CharField(required=False, allow_blank=True, max_length=180)
    site_tagline = serializers.CharField(required=False, allow_blank=True, max_length=180)
    positioning = serializers.CharField(required=False, allow_blank=True, max_length=280)
    audience = serializers.CharField(required=False, allow_blank=True, max_length=240)
    offering = serializers.CharField(required=False, allow_blank=True, max_length=240)
    tone = serializers.CharField(required=False, allow_blank=True, max_length=120)
    pages = SiteBlueprintPageSerializer(many=True)


class SiteBlueprintGenerateSerializer(serializers.Serializer):
    brief = serializers.CharField(required=False, allow_blank=True, max_length=1200)
    audience = serializers.CharField(required=False, allow_blank=True, max_length=240)
    offering = serializers.CharField(required=False, allow_blank=True, max_length=240)
    tone = serializers.CharField(required=False, allow_blank=True, max_length=120)
    keywords = serializers.ListField(
        child=serializers.CharField(max_length=80),
        required=False,
        allow_empty=True,
    )


class SiteBlueprintApplySerializer(serializers.Serializer):
    blueprint = SiteBlueprintPayloadSerializer()
    sync_navigation = serializers.BooleanField(required=False, default=True)


class BlockTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = BlockTemplate
        fields = [
            "id",
            "site",
            "name",
            "category",
            "renderer_key",
            "default_props_schema",
            "version",
            "compatibility_flags",
            "description",
            "thumbnail_url",
            "builder_data",
            "html",
            "css",
            "is_global",
            "is_premium",
            "usage_count",
            "status",
            "tags",
            "plan_required",
            "author",
            "preview_url",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["usage_count"]

    def validate(self, attrs):
        category = attrs.get("category", getattr(self.instance, "category", BlockTemplate.CATEGORY_OTHER))
        strict_renderer = "renderer_key" in attrs or self.instance is None
        renderer_key = normalize_block_template_renderer_key(
            attrs.get("renderer_key", getattr(self.instance, "renderer_key", "")),
            category=category,
            strict=strict_renderer,
        )
        attrs["renderer_key"] = renderer_key

        default_props_schema = attrs.get(
            "default_props_schema",
            getattr(self.instance, "default_props_schema", {}),
        )
        if default_props_schema is None:
            default_props_schema = {}
        if not isinstance(default_props_schema, dict):
            raise serializers.ValidationError({"default_props_schema": "Must be a JSON object."})
        attrs["default_props_schema"] = default_props_schema

        compatibility_flags = attrs.get(
            "compatibility_flags",
            getattr(self.instance, "compatibility_flags", {}),
        )
        if compatibility_flags is None:
            compatibility_flags = {}
        if not isinstance(compatibility_flags, dict):
            raise serializers.ValidationError({"compatibility_flags": "Must be a JSON object."})
        attrs["compatibility_flags"] = compatibility_flags

        version_raw = attrs.get("version", getattr(self.instance, "version", 1))
        try:
            version_value = int(version_raw)
        except (TypeError, ValueError) as exc:
            raise serializers.ValidationError({"version": "Must be an integer greater than or equal to 1."}) from exc
        if version_value < 1:
            raise serializers.ValidationError({"version": "Must be greater than or equal to 1."})
        attrs["version"] = version_value

        normalize_strict = "builder_data" in attrs
        source_builder_data = attrs.get("builder_data", getattr(self.instance, "builder_data", {}))
        normalized_builder_data = normalize_block_template_builder_data(
            source_builder_data,
            renderer_key=renderer_key,
            strict=normalize_strict,
        )
        if self.instance is None or "builder_data" in attrs:
            attrs["builder_data"] = normalized_builder_data
        return attrs


class URLRedirectSerializer(serializers.ModelSerializer):
    class Meta:
        model = URLRedirect
        fields = [
            "id",
            "site",
            "source_path",
            "target_path",
            "redirect_type",
            "status",
            "hit_count",
            "created_at",
            "updated_at",
        ]

    def validate(self, attrs):
        source_raw = attrs.get("source_path", getattr(self.instance, "source_path", ""))
        target_raw = attrs.get("target_path", getattr(self.instance, "target_path", ""))

        source = (source_raw or "").strip()
        target = (target_raw or "").strip()
        if not source:
            raise serializers.ValidationError({"source_path": "Source path is required."})
        if not target:
            raise serializers.ValidationError({"target_path": "Target path is required."})

        if not source.startswith("/"):
            source = f"/{source}"
        if source.startswith("//"):
            raise serializers.ValidationError({"source_path": "Source path cannot start with //."})
        if "?" in source or "#" in source:
            raise serializers.ValidationError({"source_path": "Source path cannot include query strings or fragments."})

        if target.startswith("/"):
            if target.startswith("//"):
                raise serializers.ValidationError({"target_path": "Target path cannot start with //."})
            attrs["source_path"] = source
            attrs["target_path"] = target
            return attrs

        parsed = urlparse(target)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise serializers.ValidationError(
                {"target_path": "Target must be a relative path or an absolute http(s) URL."}
            )
        if parsed.username or parsed.password:
            raise serializers.ValidationError({"target_path": "Target URL cannot include credentials."})
        if parsed.scheme != "https" and not settings.DEBUG:
            raise serializers.ValidationError({"target_path": "External redirect URLs must use https."})

        host = (parsed.hostname or "").strip().lower()
        allowed_external_hosts = {h.lower() for h in getattr(settings, "REDIRECT_ALLOWED_EXTERNAL_HOSTS", [])}
        if host not in allowed_external_hosts:
            raise serializers.ValidationError(
                {
                    "target_path": (
                        "External redirect host is not allowed. "
                        "Add it to DJANGO_REDIRECT_ALLOWED_EXTERNAL_HOSTS if this is intentional."
                    )
                }
            )

        attrs["source_path"] = source
        attrs["target_path"] = target
        return attrs


class DomainContactSerializer(serializers.ModelSerializer):
    class Meta:
        model = DomainContact
        fields = [
            "id",
            "site",
            "role",
            "first_name",
            "last_name",
            "email",
            "phone",
            "organization",
            "address1",
            "address2",
            "city",
            "state",
            "postal_code",
            "country",
            "created_at",
            "updated_at",
        ]


class DomainSerializer(serializers.ModelSerializer):
    expiry_status = serializers.SerializerMethodField()
    days_until_expiry = serializers.SerializerMethodField()
    registrant_contact_detail = DomainContactSerializer(source="registrant_contact", read_only=True)

    class Meta:
        model = Domain
        fields = [
            "id",
            "site",
            "domain_name",
            "is_primary",
            "status",
            "verification_method",
            "verified_at",
            "last_verification_attempt",
            "verification_error",
            "registration_status",
            "registrar",
            "registrar_account",
            "registered_at",
            "expires_at",
            "auto_renew",
            "privacy_enabled",
            "transfer_lock",
            "ssl_enabled",
            "ssl_expires_at",
            "dns_records",
            "nameservers",
            "whois_data",
            "whois_fetched_at",
            "notes",
            "tags",
            "registrant_contact",
            "registrant_contact_detail",
            "expiry_status",
            "days_until_expiry",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "verified_at",
            "last_verification_attempt",
            "verification_error",
            "whois_data",
            "whois_fetched_at",
            "expiry_status",
            "days_until_expiry",
            "registrant_contact_detail",
        ]

    def get_expiry_status(self, obj: Domain) -> str:
        from .domain_services import days_until_expiry, get_expiry_status
        expires = obj.expires_at.isoformat() if obj.expires_at else None
        days = days_until_expiry(expires)
        return get_expiry_status(days)

    def get_days_until_expiry(self, obj: Domain) -> int | None:
        from .domain_services import days_until_expiry
        expires = obj.expires_at.isoformat() if obj.expires_at else None
        return days_until_expiry(expires)


class DomainAvailabilitySerializer(serializers.ModelSerializer):
    class Meta:
        model = DomainAvailability
        fields = [
            "id",
            "domain_name",
            "available",
            "price",
            "currency",
            "registrar",
            "checked_at",
            "raw_response",
        ]
        read_only_fields = ["checked_at"]


class SEOAnalyticsSerializer(serializers.ModelSerializer):
    page_title = serializers.CharField(source="page.title", read_only=True)

    class Meta:
        model = SEOAnalytics
        fields = [
            "id",
            "site",
            "page",
            "page_title",
            "date",
            "impressions",
            "clicks",
            "average_position",
            "ctr",
            "source",
            "metadata",
            "created_at",
        ]


class MediaFolderSerializer(serializers.ModelSerializer):
    class Meta:
        model = MediaFolder
        fields = [
            "id",
            "site",
            "name",
            "parent",
            "path",
            "created_at",
            "updated_at",
        ]

    def validate(self, attrs):
        name = attrs.get("name", "")
        parent = attrs.get("parent")
        if parent:
            attrs["path"] = f"{parent.path}/{name}"
        else:
            attrs["path"] = f"/{name}"
        return attrs


class NavigationMenuSerializer(serializers.ModelSerializer):
    class Meta:
        model = NavigationMenu
        fields = [
            "id",
            "site",
            "name",
            "slug",
            "location",
            "items",
            "is_active",
            "created_at",
            "updated_at",
        ]

    def validate(self, attrs):
        name = attrs.get("name") or getattr(self.instance, "name", "menu")
        attrs["slug"] = slugify(attrs.get("slug") or name) or "menu"
        return attrs


class WebhookSerializer(serializers.ModelSerializer):
    has_secret = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Webhook
        fields = [
            "id",
            "site",
            "name",
            "url",
            "event",
            "status",
            "secret",
            "last_triggered_at",
            "success_count",
            "failure_count",
            "has_secret",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["last_triggered_at", "success_count", "failure_count", "has_secret"]
        extra_kwargs = {
            "secret": {"write_only": True, "required": False, "allow_blank": True},
        }

    def get_has_secret(self, obj) -> bool:
        return bool(obj.secret)

    def validate_url(self, value: str) -> str:
        normalized_value = (value or "").strip()
        parsed = urlparse(normalized_value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise serializers.ValidationError("Webhook URL must be an absolute http(s) URL.")
        if parsed.username or parsed.password:
            raise serializers.ValidationError("Webhook URL cannot include credentials.")
        if parsed.scheme != "https" and not settings.DEBUG:
            raise serializers.ValidationError("Webhook URL must use https in production.")

        allow_private_targets = getattr(settings, "ALLOW_PRIVATE_WEBHOOK_TARGETS", settings.DEBUG)
        hostname = (parsed.hostname or "").strip().lower()
        if hostname in {"localhost", "127.0.0.1", "::1"}:
            if not allow_private_targets:
                raise serializers.ValidationError(
                    "Webhook URL host is not allowed. Set DJANGO_ALLOW_PRIVATE_WEBHOOK_TARGETS=true to override."
                )

        try:
            ip = ipaddress.ip_address(hostname)
        except ValueError:
            normalized_hostname = hostname.rstrip(".")
            if not allow_private_targets and normalized_hostname:
                local_suffixes = (".local", ".internal", ".localhost", ".home", ".lan")
                if "." not in normalized_hostname or normalized_hostname.endswith(local_suffixes):
                    raise serializers.ValidationError(
                        "Webhook URL host must be publicly routable. "
                        "Set DJANGO_ALLOW_PRIVATE_WEBHOOK_TARGETS=true to override."
                    )
            return normalized_value

        if (
            ip.is_loopback
            or ip.is_private
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
        ) and not allow_private_targets:
            raise serializers.ValidationError(
                "Webhook URL host is private or loopback. Set DJANGO_ALLOW_PRIVATE_WEBHOOK_TARGETS=true to override."
            )
        return normalized_value


class SearchConsoleCredentialSerializer(serializers.ModelSerializer):
    is_connected = serializers.SerializerMethodField()

    class Meta:
        model = SearchConsoleCredential
        fields = [
            "id",
            "site",
            "property_url",
            "is_connected",
            "last_synced_at",
            "sync_error",
            "updated_at",
        ]
        read_only_fields = ["is_connected", "last_synced_at", "sync_error"]

    def get_is_connected(self, obj) -> bool:
        return bool(obj.access_token)


class SEOAuditSerializer(serializers.ModelSerializer):
    page_title = serializers.CharField(source="page.title", read_only=True, default="")

    class Meta:
        model = SEOAudit
        fields = [
            "id",
            "site",
            "page",
            "page_title",
            "audited_url",
            "status",
            "score",
            "title",
            "title_length",
            "meta_description",
            "meta_description_length",
            "h1_count",
            "h1_text",
            "canonical_url",
            "og_title",
            "og_description",
            "og_image",
            "response_time_ms",
            "status_code",
            "word_count",
            "image_count",
            "images_missing_alt",
            "internal_links",
            "external_links",
            "has_schema_markup",
            "is_mobile_friendly",
            "issues",
            "error_message",
            "created_at",
        ]
        read_only_fields = [
            "page_title", "status", "score", "title", "title_length",
            "meta_description", "meta_description_length", "h1_count", "h1_text",
            "canonical_url", "og_title", "og_description", "og_image",
            "response_time_ms", "status_code", "word_count", "image_count",
            "images_missing_alt", "internal_links", "external_links",
            "has_schema_markup", "is_mobile_friendly", "issues", "error_message",
        ]


class KeywordRankEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = KeywordRankEntry
        fields = [
            "id",
            "keyword",
            "date",
            "position",
            "impressions",
            "clicks",
            "url",
            "source",
        ]


class TrackedKeywordSerializer(serializers.ModelSerializer):
    rank_entries = KeywordRankEntrySerializer(many=True, read_only=True)
    latest_position = serializers.SerializerMethodField()

    class Meta:
        model = TrackedKeyword
        fields = [
            "id",
            "site",
            "keyword",
            "target_url",
            "notes",
            "is_active",
            "rank_entries",
            "latest_position",
            "created_at",
            "updated_at",
        ]

    def get_latest_position(self, obj) -> float | None:
        entry = obj.rank_entries.first()
        return entry.position if entry else None


class SEOSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = SEOSettings
        fields = [
            "id",
            "site",
            "audit_schedule",
            "alert_score_threshold",
            "gsc_property_url",
            "sitemap_url",
            "notify_on_issues",
            "updated_at",
        ]


# ---------------------------------------------------------------------------
# Workspace / Team / Membership Serializers
# ---------------------------------------------------------------------------

class UserMinimalSerializer(serializers.Serializer):
    """Minimal user representation for membership lists."""
    id = serializers.IntegerField()
    username = serializers.CharField()
    email = serializers.EmailField()


class WorkspaceMembershipSerializer(serializers.ModelSerializer):
    user = UserMinimalSerializer(read_only=True)
    user_id = serializers.IntegerField(write_only=True, required=False)
    can_manage_members = serializers.BooleanField(read_only=True)
    can_edit_content = serializers.BooleanField(read_only=True)

    class Meta:
        model = WorkspaceMembership
        fields = [
            "id",
            "workspace",
            "user",
            "user_id",
            "role",
            "can_manage_members",
            "can_edit_content",
            "invited_at",
            "accepted_at",
            "created_at",
        ]
        read_only_fields = ["workspace", "invited_at", "accepted_at"]


class WorkspaceInvitationSerializer(serializers.ModelSerializer):
    invited_by_username = serializers.CharField(source="invited_by.username", read_only=True)
    invite_url = serializers.SerializerMethodField()

    class Meta:
        model = WorkspaceInvitation
        fields = [
            "id",
            "workspace",
            "email",
            "role",
            "status",
            "invited_by",
            "invited_by_username",
            "expires_at",
            "invite_url",
            "created_at",
        ]
        read_only_fields = ["workspace", "token", "status", "invited_by", "expires_at"]

    def get_invite_url(self, obj) -> str:
        request = self.context.get("request")
        if not request:
            return f"/editor?invite_token={obj.token}"
        return request.build_absolute_uri(f"/editor?invite_token={obj.token}")


class WorkspaceSerializer(serializers.ModelSerializer):
    owner_username = serializers.CharField(source="owner.username", read_only=True)
    member_count = serializers.SerializerMethodField()
    site_count = serializers.SerializerMethodField()
    current_user_role = serializers.SerializerMethodField()

    class Meta:
        model = Workspace
        fields = [
            "id",
            "name",
            "slug",
            "description",
            "owner",
            "owner_username",
            "is_personal",
            "member_count",
            "site_count",
            "current_user_role",
            "settings",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["owner", "is_personal"]

    def get_member_count(self, obj) -> int:
        annotated = getattr(obj, "member_count", None)
        if annotated is not None:
            return int(annotated)
        return obj.memberships.count()

    def get_site_count(self, obj) -> int:
        annotated = getattr(obj, "site_count", None)
        if annotated is not None:
            return int(annotated)
        return obj.sites.count()

    def get_current_user_role(self, obj) -> str | None:
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return None
        if obj.owner_id == request.user.id:
            return WorkspaceMembership.ROLE_OWNER
        membership = obj.memberships.filter(user=request.user).first()
        return membership.role if membership else None

    def validate_settings(self, value):
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise serializers.ValidationError("Workspace settings must be a JSON object.")
        return value

    def validate_slug(self, value):
        query = Workspace.objects.filter(slug=value)
        if self.instance:
            query = query.exclude(pk=self.instance.pk)
        if query.exists():
            raise serializers.ValidationError("A workspace with this slug already exists.")
        return value


class InviteMemberSerializer(serializers.Serializer):
    """Serializer for inviting a new member to a workspace."""
    email = serializers.EmailField()
    role = serializers.ChoiceField(choices=WorkspaceMembership.ROLE_CHOICES, default=WorkspaceMembership.ROLE_EDITOR)

    def validate_role(self, value: str) -> str:
        if value == WorkspaceMembership.ROLE_OWNER:
            raise serializers.ValidationError("Invitations cannot grant owner role.")
        return value


class ChangeMemberRoleSerializer(serializers.Serializer):
    """Serializer for changing a member's role."""
    role = serializers.ChoiceField(choices=WorkspaceMembership.ROLE_CHOICES)


# Email Hosting Serializers

class EmailDomainSerializer(serializers.ModelSerializer):
    """Serializer for EmailDomain model."""
    
    dns_instructions = serializers.SerializerMethodField()
    
    class Meta:
        model = EmailDomain
        fields = [
            'id', 'site', 'workspace', 'name', 'status', 'verification_token',
            'verified_at', 'mx_record', 'spf_record', 'dkim_record', 
            'dmarc_record', 'dns_instructions', 'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'verification_token', 'verified_at', 'mx_record',
            'spf_record', 'dkim_record', 'dmarc_record', 'created_at', 'updated_at'
        ]

    def get_dns_instructions(self, obj):
        """Get DNS configuration instructions for the domain."""
        instructions = []
        if obj.mx_record:
            instructions.append({
                'type': 'MX',
                'name': '@',
                'value': obj.mx_record,
                'priority': 10
            })
        if obj.spf_record:
            instructions.append({
                'type': 'TXT',
                'name': '@',
                'value': obj.spf_record
            })
        if obj.dkim_record:
            instructions.append({
                'type': 'TXT',
                'name': 'k1._domainkey',
                'value': obj.dkim_record
            })
        if obj.dmarc_record:
            instructions.append({
                'type': 'TXT',
                'name': '_dmarc',
                'value': obj.dmarc_record
            })
        return instructions

    def validate_name(self, value):
        """Validate domain name format and uniqueness."""
        if self.instance:
            # Check if name is being changed
            if self.instance.name != value:
                if EmailDomain.objects.filter(name=value).exists():
                    raise serializers.ValidationError("Domain name already exists.")
        else:
            if EmailDomain.objects.filter(name=value).exists():
                raise serializers.ValidationError("Domain name already exists.")
        return value


class MailboxSerializer(serializers.ModelSerializer):
    """Serializer for Mailbox model."""
    
    email_address = serializers.ReadOnlyField()
    domain_name = serializers.CharField(source='domain.name', read_only=True)
    password = serializers.CharField(write_only=True, required=False)
    
    class Meta:
        model = Mailbox
        fields = [
            'id', 'workspace', 'site', 'domain', 'local_part', 'password',
            'is_active', 'quota_mb', 'last_login', 'user', 'email_address',
            'domain_name', 'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'workspace', 'site', 'last_login', 'email_address',
            'domain_name', 'created_at', 'updated_at'
        ]

    def validate_local_part(self, value):
        """Validate mailbox local part."""
        if not value:
            raise serializers.ValidationError("Local part is required.")
        
        # Check for invalid characters
        invalid_chars = [' ', '/', '\\', ':', '*', '?', '"', '<', '>', '|']
        if any(char in value for char in invalid_chars):
            raise serializers.ValidationError("Local part contains invalid characters.")
        
        # Check uniqueness within domain
        domain = self.initial_data.get('domain')
        if domain:
            try:
                domain_obj = EmailDomain.objects.get(id=domain)
                if Mailbox.objects.filter(domain=domain_obj, local_part=value).exists():
                    if not self.instance or self.instance.local_part != value:
                        raise serializers.ValidationError("Mailbox with this local part already exists for this domain.")
            except EmailDomain.DoesNotExist:
                raise serializers.ValidationError("Invalid domain.")
        
        return value

    def create(self, validated_data):
        """Create mailbox with password hashing."""
        password = validated_data.pop('password', None)
        if not password:
            raise serializers.ValidationError("Password is required.")

        validated_data['password_hash'] = make_password(password)

        return super().create(validated_data)

    def update(self, instance, validated_data):
        """Update mailbox with optional password change."""
        password = validated_data.pop('password', None)
        if password:
            validated_data['password_hash'] = make_password(password)

        return super().update(instance, validated_data)


class MailAliasSerializer(serializers.ModelSerializer):
    """Serializer for MailAlias model."""
    
    destination_email = serializers.CharField(source='destination_mailbox.email_address', read_only=True)
    
    class Meta:
        model = MailAlias
        fields = [
            'id', 'workspace', 'site', 'source_address', 'destination_mailbox',
            'destination_email', 'active', 'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'workspace', 'site', 'destination_email', 'created_at', 'updated_at'
        ]

    def validate_source_address(self, value):
        """Validate alias source address."""
        # Check uniqueness
        if MailAlias.objects.filter(source_address=value).exists():
            if not self.instance or self.instance.source_address != value:
                raise serializers.ValidationError("Alias with this source address already exists.")
        return value


class EmailProvisioningTaskSerializer(serializers.ModelSerializer):
    """Serializer for EmailProvisioningTask model."""
    
    class Meta:
        model = EmailProvisioningTask
        fields = [
            'id', 'workspace', 'task_type', 'target_id', 'status',
            'message', 'payload', 'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'workspace', 'created_at', 'updated_at'
        ]


class EmailDomainCreateSerializer(serializers.Serializer):
    """Serializer for creating a new email domain."""
    domain_name = serializers.CharField(max_length=253)
    site_id = serializers.IntegerField()
    
    def validate_domain_name(self, value):
        """Validate domain name format."""
        if not value or '.' not in value:
            raise serializers.ValidationError("Invalid domain name format.")
        
        if EmailDomain.objects.filter(name=value).exists():
            raise serializers.ValidationError("Email domain already exists.")
        
        return value

    def validate_site_id(self, value):
        """Validate site exists and belongs to user's workspace."""
        try:
            site = Site.objects.get(id=value)
            # Additional workspace validation would go here
            return value
        except Site.DoesNotExist:
            raise serializers.ValidationError("Site not found.")


class MailboxCreateSerializer(serializers.Serializer):
    """Serializer for creating a new mailbox."""
    local_part = serializers.CharField(max_length=64)
    password = serializers.CharField(min_length=8)
    quota_mb = serializers.IntegerField(default=1024, min_value=100, max_value=10240)
    domain_id = serializers.IntegerField()
    user_id = serializers.IntegerField(required=False, allow_null=True)
    
    def validate_local_part(self, value):
        """Validate mailbox local part."""
        if not value:
            raise serializers.ValidationError("Local part is required.")
        
        invalid_chars = [' ', '/', '\\', ':', '*', '?', '"', '<', '>', '|']
        if any(char in value for char in invalid_chars):
            raise serializers.ValidationError("Local part contains invalid characters.")
        
        return value

    def validate_domain_id(self, value):
        """Validate domain exists and is active."""
        try:
            domain = EmailDomain.objects.get(id=value)
            if domain.status != EmailDomain.DomainStatus.ACTIVE:
                raise serializers.ValidationError("Domain must be active to create mailboxes.")
            return value
        except EmailDomain.DoesNotExist:
            raise serializers.ValidationError("Domain not found.")
