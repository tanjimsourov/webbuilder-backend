from __future__ import annotations

from rest_framework import serializers


class WebsiteSettingsSerializer(serializers.Serializer):
    site = serializers.IntegerField()
    seo_defaults = serializers.DictField(required=False)
    branding = serializers.DictField(required=False)
    localization = serializers.DictField(required=False)
    deployment = serializers.DictField(required=False)
    robots = serializers.DictField(required=False)
    runtime = serializers.DictField(required=False)


class WebsiteDomainSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    domain_name = serializers.CharField()
    status = serializers.CharField()
    is_primary = serializers.BooleanField()
    verification_method = serializers.CharField(allow_blank=True)
    verified_at = serializers.DateTimeField(allow_null=True)
    verification_error = serializers.CharField(allow_blank=True)
    nameservers = serializers.ListField(child=serializers.CharField(), required=False)
    dns_records = serializers.DictField(required=False)


class WebsitePublishStatusSerializer(serializers.Serializer):
    site = serializers.IntegerField()
    pages_published = serializers.IntegerField()
    posts_published = serializers.IntegerField()
    products_published = serializers.IntegerField()
    last_publish_at = serializers.DateTimeField(allow_null=True)
    deployment = serializers.DictField(required=False)

