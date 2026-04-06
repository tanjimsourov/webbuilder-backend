"""Email hosting API views and viewsets."""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from builder.workspace_views import check_site_permission, get_user_workspaces
from core.views import SitePermissionMixin
from core.models import Site
from email_hosting import services as email_services
from email_hosting.models import EmailDomain, EmailProvisioningTask, MailAlias, Mailbox
from email_hosting.serializers import (
    EmailDomainCreateSerializer,
    EmailDomainSerializer,
    EmailProvisioningTaskSerializer,
    MailAliasSerializer,
    MailboxCreateSerializer,
    MailboxSerializer,
)


class EmailDomainViewSet(SitePermissionMixin, viewsets.ModelViewSet):
    serializer_class = EmailDomainSerializer
    queryset = EmailDomain.objects.select_related("site", "workspace").all()
    filterset_fields = ["site", "status", "workspace"]
    search_fields = ["name"]
    ordering_fields = ["name", "created_at", "status"]

    def get_queryset(self):
        return self.filter_by_site_permission(self.queryset)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        site = serializer.validated_data["site"]
        if not check_site_permission(request.user, site, require_edit=True):
            raise PermissionDenied("You don't have permission to edit this site.")

        try:
            domain, task = email_services.create_email_domain(
                name=serializer.validated_data["name"],
                workspace=site.workspace,
                site=site,
                queue_provisioning=True,
                queue_verification=True,
            )
        except email_services.EmailProvisioningError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        payload = self.get_serializer(domain).data
        payload["provisioning_task_id"] = task.id
        return Response(payload, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def verify(self, request, pk=None):
        domain = self.get_object()
        try:
            task = email_services.queue_domain_verification(domain.id)
        except email_services.EmailProvisioningError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            {
                "domain": domain.name,
                "task_id": task.id,
                "status": task.status,
                "message": "DNS verification queued.",
            }
        )

    @action(detail=True, methods=["get"])
    def dns_status(self, request, pk=None):
        domain = self.get_object()
        try:
            dns_status = email_services.get_domain_dns_status(domain)
        except email_services.EmailProvisioningError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(dns_status)


class MailboxViewSet(SitePermissionMixin, viewsets.ModelViewSet):
    serializer_class = MailboxSerializer
    queryset = Mailbox.objects.select_related("domain", "site", "workspace", "user").all()
    filterset_fields = ["site", "domain", "workspace", "is_active"]
    search_fields = ["local_part"]
    ordering_fields = ["local_part", "created_at", "last_login"]

    def get_queryset(self):
        return self.filter_by_site_permission(self.queryset)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        domain = serializer.validated_data["domain"]
        if not check_site_permission(request.user, domain.site, require_edit=True):
            raise PermissionDenied("You don't have permission to edit this site.")

        password = serializer.validated_data.get("password")
        if not password:
            return Response({"password": ["This field is required."]}, status=status.HTTP_400_BAD_REQUEST)

        try:
            mailbox, task = email_services.create_mailbox(
                domain=domain,
                local_part=serializer.validated_data["local_part"],
                password=password,
                user=serializer.validated_data.get("user"),
                quota_mb=serializer.validated_data.get("quota_mb", 1024),
                is_active=serializer.validated_data.get("is_active", True),
                queue_provisioning=True,
            )
        except email_services.EmailProvisioningError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        payload = self.get_serializer(mailbox).data
        payload["provisioning_task_id"] = task.id
        return Response(payload, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def reset_password(self, request, pk=None):
        mailbox = self.get_object()
        new_password = (request.data.get("password") or "").strip()
        if len(new_password) < 8:
            return Response(
                {"password": ["Password must be at least 8 characters long."]},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            mailbox, task = email_services.update_mailbox_password(mailbox, new_password)
        except email_services.EmailProvisioningError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"mailbox": mailbox.email_address, "task_id": task.id, "message": "Password reset queued."})

    @action(detail=True, methods=["post"])
    def disable(self, request, pk=None):
        mailbox = self.get_object()
        try:
            mailbox, task = email_services.disable_mailbox(mailbox)
        except email_services.EmailProvisioningError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"mailbox": mailbox.email_address, "is_active": mailbox.is_active, "task_id": task.id})

    @action(detail=True, methods=["post"])
    def enable(self, request, pk=None):
        mailbox = self.get_object()
        try:
            mailbox, task = email_services.set_mailbox_active(mailbox, is_active=True)
        except email_services.EmailProvisioningError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"mailbox": mailbox.email_address, "is_active": mailbox.is_active, "task_id": task.id})

    def destroy(self, request, *args, **kwargs):
        mailbox = self.get_object()
        try:
            email_services.delete_mailbox(mailbox)
        except email_services.EmailProvisioningError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MailAliasViewSet(SitePermissionMixin, viewsets.ModelViewSet):
    serializer_class = MailAliasSerializer
    queryset = MailAlias.objects.select_related("destination_mailbox", "site", "workspace").all()
    filterset_fields = ["site", "workspace", "destination_mailbox", "active"]
    search_fields = ["source_address"]
    ordering_fields = ["source_address", "created_at"]

    def get_queryset(self):
        return self.filter_by_site_permission(self.queryset)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        destination_mailbox = serializer.validated_data["destination_mailbox"]
        domain = destination_mailbox.domain
        if not check_site_permission(request.user, domain.site, require_edit=True):
            raise PermissionDenied("You don't have permission to edit this site.")

        try:
            alias, task = email_services.create_alias(
                domain=domain,
                source=serializer.validated_data["source_address"],
                destination_mailbox=destination_mailbox,
                active=serializer.validated_data.get("active", True),
                queue_provisioning=True,
            )
        except email_services.EmailProvisioningError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        payload = self.get_serializer(alias).data
        payload["provisioning_task_id"] = task.id
        return Response(payload, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def disable(self, request, pk=None):
        alias = self.get_object()
        try:
            alias, task = email_services.disable_alias(alias)
        except email_services.EmailProvisioningError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"alias": alias.source_address, "active": alias.active, "task_id": task.id})

    @action(detail=True, methods=["post"])
    def enable(self, request, pk=None):
        alias = self.get_object()
        try:
            alias, task = email_services.set_alias_active(alias, is_active=True)
        except email_services.EmailProvisioningError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"alias": alias.source_address, "active": alias.active, "task_id": task.id})

    def destroy(self, request, *args, **kwargs):
        alias = self.get_object()
        try:
            email_services.delete_alias(alias)
        except email_services.EmailProvisioningError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(status=status.HTTP_204_NO_CONTENT)


class EmailProvisioningTaskViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = EmailProvisioningTaskSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ["workspace", "task_type", "status"]
    ordering_fields = ["created_at", "updated_at"]

    def get_queryset(self):
        workspaces = get_user_workspaces(self.request.user)
        return EmailProvisioningTask.objects.filter(workspace__in=workspaces).order_by("-created_at")


class EmailDomainCreateView(APIView):
    """Compatibility endpoint for creating email domains."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = EmailDomainCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        workspaces = get_user_workspaces(request.user)
        site = get_object_or_404(Site.objects.select_related("workspace"), pk=serializer.validated_data["site_id"])
        if site.workspace_id not in set(workspaces.values_list("id", flat=True)):
            raise PermissionDenied("Site not found or access denied.")

        try:
            domain, task = email_services.create_email_domain(
                name=serializer.validated_data["domain_name"],
                workspace=site.workspace,
                site=site,
                queue_provisioning=True,
                queue_verification=serializer.validated_data.get("queue_verification", True),
            )
        except email_services.EmailProvisioningError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            {
                "domain": EmailDomainSerializer(domain, context={"request": request}).data,
                "task_id": task.id,
                "message": "Email domain created.",
            },
            status=status.HTTP_201_CREATED,
        )


class MailboxCreateView(APIView):
    """Compatibility endpoint for creating mailboxes."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = MailboxCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        workspaces = get_user_workspaces(request.user)
        domain = get_object_or_404(
            EmailDomain.objects.select_related("workspace", "site"),
            pk=serializer.validated_data["domain_id"],
        )
        if domain.workspace_id not in set(workspaces.values_list("id", flat=True)):
            raise PermissionDenied("Domain not found or access denied.")

        user = None
        user_id = serializer.validated_data.get("user_id")
        if user_id:
            user = get_user_model().objects.filter(pk=user_id).first()

        try:
            mailbox, task = email_services.create_mailbox(
                domain=domain,
                local_part=serializer.validated_data["local_part"],
                password=serializer.validated_data["password"],
                user=user,
                quota_mb=serializer.validated_data["quota_mb"],
                queue_provisioning=serializer.validated_data.get("queue_provisioning", True),
            )
        except email_services.EmailProvisioningError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            {
                "mailbox": MailboxSerializer(mailbox, context={"request": request}).data,
                "task_id": task.id,
                "message": "Mailbox created.",
            },
            status=status.HTTP_201_CREATED,
        )


__all__ = [
    "EmailDomainCreateView",
    "EmailDomainViewSet",
    "EmailProvisioningTaskViewSet",
    "MailAliasViewSet",
    "MailboxCreateView",
    "MailboxViewSet",
]
