"""Email hosting viewsets for SMC Web Builder."""
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.utils import timezone
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import EmailDomain, Mailbox, MailAlias, EmailProvisioningTask
from .serializers import (
    EmailDomainSerializer, MailboxSerializer, MailAliasSerializer,
    EmailProvisioningTaskSerializer, EmailDomainCreateSerializer,
    MailboxCreateSerializer
)
from .views import SitePermissionMixin


class EmailDomainViewSet(SitePermissionMixin, viewsets.ModelViewSet):
    """ViewSet for EmailDomain model."""
    
    serializer_class = EmailDomainSerializer
    filterset_fields = ['site', 'status', 'workspace']
    search_fields = ['name']
    ordering_fields = ['name', 'created_at', 'status']
    
    def get_queryset(self):
        """Filter by user's workspace."""
        from .workspace_views import get_user_workspaces
        user_workspaces = get_user_workspaces(self.request.user)
        return EmailDomain.objects.filter(workspace__in=user_workspaces)
    
    def get_site_for_object(self, obj):
        """Get site for permission checking."""
        return obj.site
    
    @action(detail=True, methods=['post'])
    def verify(self, request, pk=None):
        """Trigger DNS verification for the domain."""
        domain = self.get_object()
        
        # Create provisioning task
        task = EmailProvisioningTask.objects.create(
            workspace=domain.workspace,
            task_type=EmailProvisioningTask.TaskType.VERIFY_DOMAIN,
            target_id=str(domain.id),
            payload={'domain_name': domain.name}
        )
        
        # Update domain status
        domain.status = EmailDomain.DomainStatus.VERIFYING
        domain.verification_started_at = timezone.now()
        domain.save()
        
        return Response({
            'message': 'Domain verification started',
            'task_id': task.id
        })
    
    @action(detail=True, methods=['get'])
    def dns_status(self, request, pk=None):
        """Get current DNS verification status."""
        domain = self.get_object()
        
        # Check DNS records (simplified implementation)
        dns_status = {
            'mx': {'status': 'pending', 'message': 'Not checked'},
            'spf': {'status': 'pending', 'message': 'Not checked'},
            'dkim': {'status': 'pending', 'message': 'Not checked'},
            'dmarc': {'status': 'pending', 'message': 'Not checked'}
        }
        
        return Response({
            'domain': domain.name,
            'status': domain.status,
            'records': dns_status,
            'verified_at': domain.verified_at
        })
    
    def perform_create(self, serializer):
        """Create email domain with workspace and site."""
        # Get workspace from site
        site = serializer.validated_data['site']
        workspace = site.workspace
        
        # Generate DNS records
        domain_name = serializer.validated_data['name']
        mx_record = f"mail.{domain_name}."
        spf_record = f"v=spf1 mx include:{domain_name} ~all"
        dkim_record = "v=DKIM1; k=rsa; p=MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA"
        dmarc_record = "v=DMARC1; p=quarantine; rua=mailto:dmarc@" + domain_name
        
        serializer.save(
            workspace=workspace,
            mx_record=mx_record,
            spf_record=spf_record,
            dkim_record=dkim_record,
            dmarc_record=dmarc_record
        )


class MailboxViewSet(SitePermissionMixin, viewsets.ModelViewSet):
    """ViewSet for Mailbox model."""
    
    serializer_class = MailboxSerializer
    filterset_fields = ['site', 'domain', 'workspace', 'is_active']
    search_fields = ['local_part']
    ordering_fields = ['local_part', 'created_at', 'last_login']
    
    def get_queryset(self):
        """Filter by user's workspace."""
        from .workspace_views import get_user_workspaces
        user_workspaces = get_user_workspaces(self.request.user)
        return Mailbox.objects.filter(workspace__in=user_workspaces)
    
    def get_site_for_object(self, obj):
        """Get site for permission checking."""
        return obj.site
    
    @action(detail=True, methods=['post'])
    def reset_password(self, request, pk=None):
        """Reset mailbox password."""
        mailbox = self.get_object()
        new_password = request.data.get('password')
        
        if not new_password or len(new_password) < 8:
            return Response(
                {'error': 'Password must be at least 8 characters long'},
                status=status.HTTP_400_BAD_REQUEST
            )

        mailbox.password_hash = make_password(new_password)
        mailbox.save()
        
        # Create provisioning task
        task = EmailProvisioningTask.objects.create(
            workspace=mailbox.workspace,
            task_type=EmailProvisioningTask.TaskType.UPDATE_MAILBOX,
            target_id=str(mailbox.id),
            payload={'password_reset': True}
        )
        
        return Response({
            'message': 'Password reset successful',
            'task_id': task.id
        })
    
    @action(detail=True, methods=['post'])
    def toggle_status(self, request, pk=None):
        """Toggle mailbox active status."""
        mailbox = self.get_object()
        mailbox.is_active = not mailbox.is_active
        mailbox.save()
        
        task_type = (EmailProvisioningTask.TaskType.ACTIVATE_MAILBOX 
                    if mailbox.is_active 
                    else EmailProvisioningTask.TaskType.SUSPEND_MAILBOX)
        
        # Create provisioning task
        task = EmailProvisioningTask.objects.create(
            workspace=mailbox.workspace,
            task_type=task_type,
            target_id=str(mailbox.id)
        )
        
        return Response({
            'message': f'Mailbox {"activated" if mailbox.is_active else "suspended"}',
            'is_active': mailbox.is_active,
            'task_id': task.id
        })
    
    def perform_create(self, serializer):
        """Create mailbox with workspace and site."""
        domain = serializer.validated_data['domain']
        serializer.save(
            workspace=domain.workspace,
            site=domain.site
        )


class MailAliasViewSet(SitePermissionMixin, viewsets.ModelViewSet):
    """ViewSet for MailAlias model."""
    
    serializer_class = MailAliasSerializer
    filterset_fields = ['site', 'workspace', 'destination_mailbox', 'active']
    search_fields = ['source_address']
    ordering_fields = ['source_address', 'created_at']
    
    def get_queryset(self):
        """Filter by user's workspace."""
        from .workspace_views import get_user_workspaces
        user_workspaces = get_user_workspaces(self.request.user)
        return MailAlias.objects.filter(workspace__in=user_workspaces)
    
    def get_site_for_object(self, obj):
        """Get site for permission checking."""
        return obj.site
    
    def perform_create(self, serializer):
        """Create alias with workspace and site."""
        destination_mailbox = serializer.validated_data['destination_mailbox']
        serializer.save(
            workspace=destination_mailbox.workspace,
            site=destination_mailbox.site
        )


class EmailProvisioningTaskViewSet(SitePermissionMixin, viewsets.ReadOnlyModelViewSet):
    """ViewSet for EmailProvisioningTask model (read-only)."""
    
    serializer_class = EmailProvisioningTaskSerializer
    filterset_fields = ['workspace', 'task_type', 'status']
    ordering_fields = ['created_at', 'updated_at']
    
    def get_queryset(self):
        """Filter by user's workspace."""
        from .workspace_views import get_user_workspaces
        user_workspaces = get_user_workspaces(self.request.user)
        return EmailProvisioningTask.objects.filter(workspace__in=user_workspaces)


class EmailHostingAPIView(APIView):
    """Base API view for email hosting operations."""
    
    permission_classes = [permissions.IsAuthenticated]
    
    def get_workspace(self):
        """Get current workspace from request."""
        from .workspace_views import get_user_workspaces
        user_workspaces = get_user_workspaces(self.request.user)
        workspace_id = self.request.data.get('workspace_id') or self.request.query_params.get('workspace_id')
        
        if workspace_id:
            try:
                workspace = user_workspaces.get(id=workspace_id)
                return workspace
            except Exception:
                raise PermissionDenied("Invalid workspace")
        
        # Return first workspace if none specified
        if user_workspaces.exists():
            return user_workspaces.first()
        
        raise PermissionDenied("No workspace found")


class EmailDomainCreateView(EmailHostingAPIView):
    """Create a new email domain."""
    
    def post(self, request):
        """Create email domain for a site."""
        serializer = EmailDomainCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        workspace = self.get_workspace()
        
        # Get site
        try:
            from .models import Site
            site = Site.objects.get(
                id=serializer.validated_data['site_id'],
                workspace=workspace
            )
        except Site.DoesNotExist:
            return Response(
                {'error': 'Site not found or access denied'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Create email domain
        domain = EmailDomain.objects.create(
            name=serializer.validated_data['domain_name'],
            site=site,
            workspace=workspace,
            mx_record=f"mail.{serializer.validated_data['domain_name']}.",
            spf_record=f"v=spf1 mx include:{serializer.validated_data['domain_name']} ~all",
            dkim_record="v=DKIM1; k=rsa; p=MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA",
            dmarc_record=f"v=DMARC1; p=quarantine; rua=mailto:dmarc@{serializer.validated_data['domain_name']}"
        )
        
        # Create provisioning task
        task = EmailProvisioningTask.objects.create(
            workspace=workspace,
            task_type=EmailProvisioningTask.TaskType.CREATE_DOMAIN,
            target_id=str(domain.id),
            payload={'domain_name': domain.name}
        )
        
        return Response({
            'domain': EmailDomainSerializer(domain).data,
            'task_id': task.id,
            'message': 'Email domain created successfully'
        }, status=status.HTTP_201_CREATED)


class MailboxCreateView(EmailHostingAPIView):
    """Create a new mailbox."""
    
    def post(self, request):
        """Create mailbox in an email domain."""
        serializer = MailboxCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        workspace = self.get_workspace()
        
        # Get domain
        try:
            domain = EmailDomain.objects.get(
                id=serializer.validated_data['domain_id'],
                workspace=workspace,
                status=EmailDomain.DomainStatus.ACTIVE
            )
        except EmailDomain.DoesNotExist:
            return Response(
                {'error': 'Domain not found, not active, or access denied'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Check for existing mailbox
        if Mailbox.objects.filter(
            domain=domain,
            local_part=serializer.validated_data['local_part']
        ).exists():
            return Response(
                {'error': 'Mailbox with this local part already exists'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Get user if specified
        user = None
        user_id = serializer.validated_data.get('user_id')
        if user_id:
            try:
                user = get_user_model().objects.get(id=user_id)
            except get_user_model().DoesNotExist:
                pass
        
        # Create mailbox
        mailbox = Mailbox.objects.create(
            domain=domain,
            site=domain.site,
            workspace=workspace,
            local_part=serializer.validated_data['local_part'],
            password_hash=make_password(serializer.validated_data['password']),
            quota_mb=serializer.validated_data['quota_mb'],
            user=user
        )
        
        # Create provisioning task
        task = EmailProvisioningTask.objects.create(
            workspace=workspace,
            task_type=EmailProvisioningTask.TaskType.CREATE_MAILBOX,
            target_id=str(mailbox.id),
            payload={
                'email_address': mailbox.email_address,
                'quota_mb': mailbox.quota_mb
            }
        )
        
        return Response({
            'mailbox': MailboxSerializer(mailbox).data,
            'task_id': task.id,
            'message': 'Mailbox created successfully'
        }, status=status.HTTP_201_CREATED)
