"""CMS domain serializers, including public runtime payloads."""

from __future__ import annotations

from rest_framework import serializers

from cms.models import NavigationMenu

from builder.serializers import (  # noqa: F401
    AssetUsageReferenceSerializer,
    BlockTemplateSerializer,
    BuilderSaveSerializer,
    CollaboratorUserSerializer,
    DomainAvailabilitySerializer,
    DomainContactSerializer,
    DomainSerializer,
    MediaAssetSerializer,
    MediaFolderSerializer,
    NavigationMenuSerializer,
    PageExperimentSerializer,
    PageExperimentVariantSerializer,
    PageRevisionSerializer,
    PageReviewCommentSerializer,
    PageReviewSerializer,
    PageSerializer,
    PageTranslationSerializer,
    PreviewTokenSerializer,
    PublishSnapshotSerializer,
    ReusableSectionSerializer,
    SiteShellSerializer,
    SiteMirrorImportSerializer,
    ThemeTemplateSerializer,
    URLRedirectSerializer,
)


class PublicRuntimeLocaleSerializer(serializers.Serializer):
    """Locale payload used by the headless runtime."""

    code = serializers.CharField()
    direction = serializers.CharField()
    is_default = serializers.BooleanField()


class PublicRuntimeSiteIdentitySerializer(serializers.Serializer):
    """Minimal site identity for domain->site runtime resolution."""

    id = serializers.IntegerField()
    slug = serializers.CharField()
    name = serializers.CharField()
    tagline = serializers.CharField(allow_blank=True)
    description = serializers.CharField(allow_blank=True)
    matched_domain = serializers.CharField(allow_blank=True)
    canonical_domain = serializers.CharField(allow_blank=True)
    resolution_source = serializers.CharField(allow_blank=True)
    locales = PublicRuntimeLocaleSerializer(many=True)
    capabilities = serializers.DictField()


class PublicRuntimeMenuSerializer(serializers.ModelSerializer):
    """Menu payload designed for renderer consumption only."""

    class Meta:
        model = NavigationMenu
        fields = [
            "id",
            "name",
            "slug",
            "location",
            "items",
        ]


class PublicRuntimeSiteSettingsSerializer(serializers.Serializer):
    """Public theme/settings contract for headless rendering."""

    site = serializers.DictField()
    settings = serializers.DictField()


class PublicRuntimeSectionVisibilityRuleSerializer(serializers.Serializer):
    """Visibility rule contract for one section."""

    type = serializers.CharField()
    value = serializers.JSONField(required=False, allow_null=True)
    operator = serializers.CharField(required=False, allow_blank=True)


class PublicRuntimeSectionVisibilitySerializer(serializers.Serializer):
    """Visibility config consumed by the section renderer."""

    enabled = serializers.BooleanField()
    audience = serializers.ListField(child=serializers.CharField(), required=False)
    rules = PublicRuntimeSectionVisibilityRuleSerializer(many=True, required=False)


class PublicRuntimeSectionDataSourceSerializer(serializers.Serializer):
    """Runtime data source declaration used by registry components."""

    type = serializers.CharField()
    ref = serializers.CharField(required=False, allow_blank=True)
    params = serializers.DictField(required=False)


class PublicRuntimeSectionContractSerializer(serializers.Serializer):
    """Explicit section contract shape for Next.js component registry rendering."""

    id = serializers.CharField()
    type = serializers.CharField()
    component = serializers.CharField()
    component_version = serializers.IntegerField()
    ordering = serializers.IntegerField()
    slot = serializers.CharField(required=False, allow_blank=True)
    props = serializers.DictField()
    content = serializers.DictField()
    layout = serializers.DictField()
    style_tokens = serializers.DictField()
    visibility = PublicRuntimeSectionVisibilitySerializer()
    data_source = PublicRuntimeSectionDataSourceSerializer(required=False)
    children = serializers.SerializerMethodField()

    def get_children(self, obj):
        children = obj.get("children") if isinstance(obj, dict) else []
        if not isinstance(children, list):
            return []
        return PublicRuntimeSectionContractSerializer(children, many=True).data


class PublicRuntimeSectionContractMetaSerializer(serializers.Serializer):
    """Metadata describing the section contract version for this page payload."""

    version = serializers.IntegerField()
    registry = serializers.CharField()
    allowed_data_sources = serializers.ListField(child=serializers.CharField(), required=False)


class PublicRuntimeComponentRegistryEntrySerializer(serializers.Serializer):
    """One allowed component key for runtime registry-driven rendering."""

    key = serializers.CharField()
    label = serializers.CharField()
    category = serializers.CharField()
    data_sources = serializers.ListField(child=serializers.CharField(), required=False)


class PublicRuntimePageSerializer(serializers.Serializer):
    """Published page payload for Next.js page rendering."""

    id = serializers.IntegerField()
    page_id = serializers.IntegerField()
    translation_id = serializers.IntegerField(allow_null=True)
    title = serializers.CharField()
    path = serializers.CharField()
    is_homepage = serializers.BooleanField()
    locale = serializers.CharField(allow_blank=True)
    is_translation = serializers.BooleanField()
    builder_schema_version = serializers.IntegerField()
    builder_data = serializers.DictField()
    section_contract = PublicRuntimeSectionContractMetaSerializer()
    sections = PublicRuntimeSectionContractSerializer(many=True)
    component_registry = PublicRuntimeComponentRegistryEntrySerializer(many=True)
    page_settings = serializers.DictField()
    seo = serializers.DictField()
    html = serializers.CharField()
    css = serializers.CharField()
    js = serializers.CharField()
    updated_at = serializers.DateTimeField()


class PublicRuntimeSitemapEntrySerializer(serializers.Serializer):
    """Sitemap item payload exposed through JSON runtime APIs."""

    kind = serializers.CharField()
    path = serializers.CharField()
    locale = serializers.CharField(allow_blank=True)
    last_modified = serializers.DateTimeField()


__all__ = [
    "BlockTemplateSerializer",
    "BuilderSaveSerializer",
    "CollaboratorUserSerializer",
    "AssetUsageReferenceSerializer",
    "DomainAvailabilitySerializer",
    "DomainContactSerializer",
    "DomainSerializer",
    "MediaAssetSerializer",
    "MediaFolderSerializer",
    "NavigationMenuSerializer",
    "PageExperimentSerializer",
    "PageExperimentVariantSerializer",
    "PageRevisionSerializer",
    "PageReviewCommentSerializer",
    "PageReviewSerializer",
    "PageSerializer",
    "PageTranslationSerializer",
    "PreviewTokenSerializer",
    "PublishSnapshotSerializer",
    "ReusableSectionSerializer",
    "SiteShellSerializer",
    "SiteMirrorImportSerializer",
    "ThemeTemplateSerializer",
    "URLRedirectSerializer",
    "PublicRuntimeLocaleSerializer",
    "PublicRuntimeMenuSerializer",
    "PublicRuntimePageSerializer",
    "PublicRuntimeComponentRegistryEntrySerializer",
    "PublicRuntimeSectionContractMetaSerializer",
    "PublicRuntimeSectionContractSerializer",
    "PublicRuntimeSectionDataSourceSerializer",
    "PublicRuntimeSectionVisibilityRuleSerializer",
    "PublicRuntimeSectionVisibilitySerializer",
    "PublicRuntimeSiteIdentitySerializer",
    "PublicRuntimeSiteSettingsSerializer",
    "PublicRuntimeSitemapEntrySerializer",
]
