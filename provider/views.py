from __future__ import annotations

from datetime import timedelta

from django.db.models import Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import Site, Workspace
from provider.models import AIJob, AIUsageQuota, AIUsageRecord
from provider.serializers import AIGenerationRequestSerializer, AIJobSerializer, AIUsageSummarySerializer
from provider.services import providers
from shared.policies.access import SitePermission, WorkspacePermission, has_site_permission, has_workspace_permission


class ProviderCatalogView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(
            {
                "storage": providers.storage.__class__.__name__,
                "image": providers.image.__class__.__name__,
                "email": providers.email.__class__.__name__,
                "search": providers.search.__class__.__name__,
                "dns": providers.dns.__class__.__name__,
                "payment": providers.payment.__class__.__name__,
                "shipping": providers.shipping.__class__.__name__,
                "tax": providers.tax.__class__.__name__,
                "ai": providers.ai.__class__.__name__,
            }
        )


class ImageTransformView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def get(self, request):
        source = (request.query_params.get("src") or "").strip()
        width = request.query_params.get("w")
        height = request.query_params.get("h")
        quality = request.query_params.get("q")
        fit = request.query_params.get("fit")
        if not source:
            return Response({"detail": "src query parameter is required."}, status=400)
        transformed = providers.image.build_url(source, w=width, h=height, q=quality, fit=fit)
        return Response({"source": source, "transformed": transformed})


class DNSVerificationInstructionsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        domain_name = (request.data.get("domain_name") or "").strip().lower()
        token = (request.data.get("token") or "").strip()
        if not domain_name or not token:
            return Response({"detail": "domain_name and token are required."}, status=400)
        instructions = providers.dns.verification_instructions(domain_name, token)
        return Response({"domain_name": domain_name, "instructions": instructions})


class AIScopeMixin:
    permission_classes = [permissions.IsAuthenticated]

    def _resolve_scope(self, request, payload: dict):
        site = None
        workspace = None
        site_id = payload.get("site")
        workspace_id = payload.get("workspace")
        if site_id:
            site = get_object_or_404(Site.objects.select_related("workspace"), pk=site_id)
            if not has_site_permission(request.user, site, SitePermission.EDIT):
                raise PermissionDenied("You don't have permission to run AI for this site.")
            workspace = site.workspace
        elif workspace_id:
            workspace = get_object_or_404(Workspace, pk=workspace_id)
            if not has_workspace_permission(request.user, workspace, WorkspacePermission.EDIT):
                raise PermissionDenied("You don't have permission to run AI for this workspace.")
        return site, workspace

    def _submit(self, request, *, forced_feature: str | None = None):
        serializer = AIGenerationRequestSerializer(data=request.data if isinstance(request.data, dict) else {})
        serializer.is_valid(raise_exception=True)
        site, workspace = self._resolve_scope(request, serializer.validated_data)
        feature = forced_feature or serializer.validated_data.get("feature")
        if not feature:
            return Response({"detail": "feature is required."}, status=status.HTTP_400_BAD_REQUEST)
        ai_job = providers.ai.submit_job(
            feature=feature,
            prompt=serializer.validated_data["prompt"],
            input_payload=serializer.validated_data.get("input_payload") or {},
            workspace=workspace,
            site=site,
            requested_by=request.user,
            provider=serializer.validated_data.get("provider", ""),
            model_name=serializer.validated_data.get("model_name", ""),
            queue=serializer.validated_data.get("queue", True),
            metadata={"source": "provider.ai.api"},
        )
        return Response(AIJobSerializer(ai_job).data, status=status.HTTP_202_ACCEPTED)


class AIGenerationView(AIScopeMixin, APIView):
    def post(self, request):
        return self._submit(request)


class AIPageOutlineView(AIScopeMixin, APIView):
    def post(self, request):
        return self._submit(request, forced_feature=AIJob.FEATURE_PAGE_OUTLINE)


class AIBlogDraftView(AIScopeMixin, APIView):
    def post(self, request):
        return self._submit(request, forced_feature=AIJob.FEATURE_BLOG_DRAFT)


class AIProductDescriptionView(AIScopeMixin, APIView):
    def post(self, request):
        return self._submit(request, forced_feature=AIJob.FEATURE_PRODUCT_DESCRIPTION)


class AISEOMetadataView(AIScopeMixin, APIView):
    def post(self, request):
        return self._submit(request, forced_feature=AIJob.FEATURE_SEO_META)


class AIImageAltTextView(AIScopeMixin, APIView):
    def post(self, request):
        return self._submit(request, forced_feature=AIJob.FEATURE_IMAGE_ALT_TEXT)


class AIFAQSchemaView(AIScopeMixin, APIView):
    def post(self, request):
        return self._submit(request, forced_feature=AIJob.FEATURE_FAQ_SCHEMA)


class AISectionCompositionView(AIScopeMixin, APIView):
    def post(self, request):
        return self._submit(request, forced_feature=AIJob.FEATURE_SECTION_COMPOSITION)


class AIJobListView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        site_id = request.query_params.get("site")
        workspace_id = request.query_params.get("workspace")
        queryset = AIJob.objects.select_related("site", "workspace", "requested_by", "queue_job").order_by("-created_at")
        if site_id:
            site = get_object_or_404(Site.objects.select_related("workspace"), pk=site_id)
            if not has_site_permission(request.user, site, SitePermission.VIEW):
                raise PermissionDenied("No access to this site.")
            queryset = queryset.filter(site_id=site.id)
        elif workspace_id:
            workspace = get_object_or_404(Workspace, pk=workspace_id)
            if not has_workspace_permission(request.user, workspace, WorkspacePermission.VIEW):
                raise PermissionDenied("No access to this workspace.")
            queryset = queryset.filter(workspace_id=workspace.id)
        else:
            queryset = queryset.none()
        status_filter = (request.query_params.get("status") or "").strip()
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        return Response(AIJobSerializer(queryset[:100], many=True).data)


class AIJobDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, job_id: int):
        ai_job = get_object_or_404(AIJob.objects.select_related("site", "workspace"), pk=job_id)
        if ai_job.site_id:
            if not has_site_permission(request.user, ai_job.site, SitePermission.VIEW):
                raise PermissionDenied("No access to this site.")
        elif ai_job.workspace_id:
            if not has_workspace_permission(request.user, ai_job.workspace, WorkspacePermission.VIEW):
                raise PermissionDenied("No access to this workspace.")
        else:
            raise PermissionDenied("No access to this job.")
        return Response(AIJobSerializer(ai_job).data)


class AIUsageSummaryView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        serializer = AIUsageSummarySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        site = None
        workspace = None
        if serializer.validated_data.get("site"):
            site = get_object_or_404(Site.objects.select_related("workspace"), pk=serializer.validated_data["site"])
            if not has_site_permission(request.user, site, SitePermission.VIEW):
                raise PermissionDenied("No access to this site.")
            workspace = site.workspace
        elif serializer.validated_data.get("workspace"):
            workspace = get_object_or_404(Workspace, pk=serializer.validated_data["workspace"])
            if not has_workspace_permission(request.user, workspace, WorkspacePermission.VIEW):
                raise PermissionDenied("No access to this workspace.")
        else:
            return Response({"detail": "site or workspace is required."}, status=status.HTTP_400_BAD_REQUEST)

        days = serializer.validated_data["days"]
        since = timezone.now() - timedelta(days=days)
        records = AIUsageRecord.objects.filter(created_at__gte=since)
        quotas = AIUsageQuota.objects.filter(is_active=True)
        if site:
            records = records.filter(site=site)
            quotas = quotas.filter(site=site)
        if workspace:
            records = records.filter(workspace=workspace)
            quotas = quotas.filter(workspace=workspace)

        usage_summary = records.aggregate(
            request_count=Sum("request_count"),
            prompt_tokens=Sum("prompt_tokens"),
            completion_tokens=Sum("completion_tokens"),
            total_tokens=Sum("total_tokens"),
            total_cost_usd=Sum("cost_usd"),
        )
        by_feature = list(
            records.values("feature")
            .annotate(request_count=Sum("request_count"), total_tokens=Sum("total_tokens"), total_cost_usd=Sum("cost_usd"))
            .order_by("-request_count")
        )
        return Response(
            {
                "scope": {
                    "site": site.id if site else None,
                    "workspace": workspace.id if workspace else None,
                    "days": days,
                },
                "usage_summary": usage_summary,
                "by_feature": by_feature,
                "quotas": [
                    {
                        "id": quota.id,
                        "feature": quota.feature,
                        "period": quota.period,
                        "max_requests": quota.max_requests,
                        "max_tokens": quota.max_tokens,
                        "max_cost_usd": str(quota.max_cost_usd),
                        "reset_at": quota.reset_at,
                        "is_active": quota.is_active,
                    }
                    for quota in quotas.order_by("feature")
                ],
            }
        )
