from __future__ import annotations

from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from django.shortcuts import get_object_or_404

from .ai_services import AI_GOALS, ai_service, apply_site_blueprint
from .app_registry import platform_app_registry
from .models import Page, Site
from .serializers import PageSerializer, SiteBlueprintApplySerializer, SiteBlueprintGenerateSerializer, SiteSerializer
from .workspace_views import check_site_permission


class AppsCatalogView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response({"apps": platform_app_registry.list_apps()})


class AISuggestionView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        goal = str(request.data.get("goal", "")).strip()
        if goal not in AI_GOALS:
            return Response(
                {"detail": f"goal must be one of: {', '.join(sorted(AI_GOALS))}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        site_id = request.data.get("site_id") or request.data.get("site")
        if not site_id:
            return Response({"detail": "site_id is required."}, status=status.HTTP_400_BAD_REQUEST)

        site = get_object_or_404(Site, pk=site_id)
        if not check_site_permission(request.user, site, require_edit=True):
            return Response({"detail": "You don't have permission to edit this site."}, status=status.HTTP_403_FORBIDDEN)

        page = None
        page_id = request.data.get("page_id") or request.data.get("page")
        if page_id:
            page = get_object_or_404(Page.objects.select_related("site"), pk=page_id, site=site)

        keywords_raw = request.data.get("keywords", [])
        if isinstance(keywords_raw, str):
            keywords = [item.strip() for item in keywords_raw.split(",") if item.strip()]
        elif isinstance(keywords_raw, list):
            keywords = [str(item).strip() for item in keywords_raw if str(item).strip()]
        else:
            keywords = []

        payload = {
            "brief": str(request.data.get("brief", "")).strip(),
            "keywords": keywords,
        }

        return Response(ai_service.generate(goal=goal, site=site, page=page, payload=payload))


class AISiteBlueprintView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        site_id = request.data.get("site_id") or request.data.get("site")
        if not site_id:
            return Response({"detail": "site_id is required."}, status=status.HTTP_400_BAD_REQUEST)

        site = get_object_or_404(Site, pk=site_id)
        if not check_site_permission(request.user, site, require_edit=True):
            return Response({"detail": "You don't have permission to edit this site."}, status=status.HTTP_403_FORBIDDEN)

        serializer = SiteBlueprintGenerateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(ai_service.generate_site_blueprint(site=site, payload=serializer.validated_data))


class AISiteBlueprintApplyView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        site_id = request.data.get("site_id") or request.data.get("site")
        if not site_id:
            return Response({"detail": "site_id is required."}, status=status.HTTP_400_BAD_REQUEST)

        site = get_object_or_404(Site, pk=site_id)
        if not check_site_permission(request.user, site, require_edit=True):
            return Response({"detail": "You don't have permission to edit this site."}, status=status.HTTP_403_FORBIDDEN)

        serializer = SiteBlueprintApplySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = apply_site_blueprint(
            site=site,
            blueprint=serializer.validated_data["blueprint"],
            sync_navigation=serializer.validated_data["sync_navigation"],
        )
        site.refresh_from_db()
        return Response(
            {
                "site": SiteSerializer(site, context={"request": request}).data,
                "created_pages": PageSerializer(result["created_pages"], many=True, context={"request": request}).data,
                "existing_pages": PageSerializer(result["existing_pages"], many=True, context={"request": request}).data,
                "homepage_page_id": result["homepage_page_id"],
                "navigation_synced": result["navigation_synced"],
                "blueprint": result["blueprint"],
            }
        )
