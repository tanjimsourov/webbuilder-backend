"""
Notification Services - Multi-channel notification system

Provides email and webhook notifications with templates and workflows.
Inspired by Novu patterns but adapted to our Django stack.
"""

import json
import logging
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional
from django.core.mail import send_mail
from django.template import Template, Context
from django.conf import settings

logger = logging.getLogger(__name__)


class NotificationChannel:
    """Base class for notification channels."""
    
    def send(self, recipient: str, subject: str, content: str, metadata: Dict = None) -> bool:
        raise NotImplementedError


class EmailChannel(NotificationChannel):
    """Email notification channel."""
    
    def send(self, recipient: str, subject: str, content: str, metadata: Dict = None) -> bool:
        try:
            from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@smcwebbuilder.com')
            send_mail(
                subject=subject,
                message=content,
                from_email=from_email,
                recipient_list=[recipient],
                fail_silently=False,
            )
            logger.info(f"Email sent to {recipient}: {subject}")
            return True
        except Exception as e:
            logger.error(f"Failed to send email to {recipient}: {e}")
            return False


class WebhookChannel(NotificationChannel):
    """Webhook notification channel."""
    
    def send(self, recipient: str, subject: str, content: str, metadata: Dict = None) -> bool:
        try:
            payload = {
                "event": subject,
                "data": content,
                "metadata": metadata or {},
            }
            request = urllib.request.Request(
                recipient,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=10) as response:
                status_code = response.status

            if status_code < 400:
                logger.info(f"Webhook sent to {recipient}: {subject}")
                return True
            logger.error(f"Webhook failed: {status_code}")
            return False
        except urllib.error.HTTPError as e:
            logger.error(f"Webhook failed: {e.code}")
            return False
        except Exception as e:
            logger.error(f"Failed to send webhook to {recipient}: {e}")
            return False


class NotificationTemplate:
    """Notification template with variable substitution."""
    
    def __init__(self, name: str, subject_template: str, body_template: str):
        self.name = name
        self.subject_template = subject_template
        self.body_template = body_template
    
    def render(self, context: Dict[str, Any]) -> tuple[str, str]:
        """Render template with context variables."""
        try:
            subject = Template(self.subject_template).render(Context(context))
            body = Template(self.body_template).render(Context(context))
            return subject, body
        except Exception as e:
            logger.error(f"Failed to render template {self.name}: {e}")
            return self.subject_template, self.body_template


class NotificationService:
    """
    Multi-channel notification service.
    
    Features:
    - Email notifications
    - Webhook notifications
    - Template system
    - Workflow triggers
    """
    
    def __init__(self):
        self.channels = {
            'email': EmailChannel(),
            'webhook': WebhookChannel(),
        }
        self.templates = self._load_templates()
    
    def _load_templates(self) -> Dict[str, NotificationTemplate]:
        """Load notification templates."""
        return {
            'order_placed': NotificationTemplate(
                name='order_placed',
                subject_template='Order #{{ order_number }} Placed',
                body_template='''
Hello {{ customer_name }},

Thank you for your order!

Order Number: {{ order_number }}
Total: ${{ total }}
Status: {{ status }}

We'll send you another email when your order ships.

Best regards,
{{ site_name }}
                '''.strip()
            ),
            'order_paid': NotificationTemplate(
                name='order_paid',
                subject_template='Payment Received for Order #{{ order_number }}',
                body_template='''
Hello {{ customer_name }},

We've received your payment for order #{{ order_number }}.

Amount: ${{ total }}
Payment Method: {{ payment_method }}

Your order is now being processed.

Best regards,
{{ site_name }}
                '''.strip()
            ),
            'order_fulfilled': NotificationTemplate(
                name='order_fulfilled',
                subject_template='Order #{{ order_number }} Shipped',
                body_template='''
Hello {{ customer_name }},

Great news! Your order has been shipped.

Order Number: {{ order_number }}
Tracking Number: {{ tracking_number }}

You should receive your order within {{ estimated_days }} business days.

Best regards,
{{ site_name }}
                '''.strip()
            ),
            'form_submission': NotificationTemplate(
                name='form_submission',
                subject_template='New Form Submission: {{ form_name }}',
                body_template='''
New form submission received:

Form: {{ form_name }}
Submitted: {{ submitted_at }}

{{ submission_data }}

View in admin: {{ admin_url }}
                '''.strip()
            ),
            'workspace_invitation': NotificationTemplate(
                name='workspace_invitation',
                subject_template='You\'ve been invited to {{ workspace_name }}',
                body_template='''
Hello,

{{ inviter_name }} has invited you to join {{ workspace_name }} on SMC Web Builder.

Role: {{ role }}

Click here to accept: {{ invitation_url }}

This invitation expires in {{ expiry_days }} days.

Best regards,
SMC Web Builder Team
                '''.strip()
            ),
            'page_published': NotificationTemplate(
                name='page_published',
                subject_template='Page Published: {{ page_title }}',
                body_template='''
The page "{{ page_title }}" has been published.

Site: {{ site_name }}
URL: {{ page_url }}
Published by: {{ user_name }}
Published at: {{ published_at }}
                '''.strip()
            ),
        }
    
    def send_notification(
        self,
        template_name: str,
        channel: str,
        recipient: str,
        context: Dict[str, Any],
        metadata: Optional[Dict] = None
    ) -> bool:
        """
        Send a notification using a template.
        
        Args:
            template_name: Name of the template to use
            channel: Channel to send through (email, webhook)
            recipient: Recipient address (email or webhook URL)
            context: Template context variables
            metadata: Additional metadata for the notification
        
        Returns:
            True if sent successfully
        """
        if channel not in self.channels:
            logger.error(f"Unknown channel: {channel}")
            return False
        
        if template_name not in self.templates:
            logger.error(f"Unknown template: {template_name}")
            return False
        
        template = self.templates[template_name]
        subject, body = template.render(context)
        
        channel_obj = self.channels[channel]
        return channel_obj.send(recipient, subject, body, metadata)
    
    def send_order_notification(
        self,
        order,
        event: str,
        customer_email: Optional[str] = None
    ) -> bool:
        """Send order-related notification."""
        template_map = {
            'placed': 'order_placed',
            'paid': 'order_paid',
            'fulfilled': 'order_fulfilled',
        }
        
        template_name = template_map.get(event)
        if not template_name:
            logger.error(f"Unknown order event: {event}")
            return False
        
        context = {
            'order_number': order.order_number,
            'customer_name': order.customer_name,
            'total': str(order.total),
            'status': order.status,
            'payment_method': order.payment_provider or 'Card',
            'tracking_number': str((order.pricing_details or {}).get('tracking_number') or 'TBD'),
            'estimated_days': '3-5',
            'site_name': order.site.name,
        }
        
        recipient = customer_email or order.customer_email
        if not recipient:
            logger.warning(f"No email for order {order.order_number}")
            return False
        
        return self.send_notification(
            template_name=template_name,
            channel='email',
            recipient=recipient,
            context=context
        )
    
    def send_form_submission_notification(
        self,
        form,
        submission,
        admin_emails: List[str]
    ) -> bool:
        """Send form submission notification to admins."""
        context = {
            'form_name': form.name,
            'submitted_at': submission.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'submission_data': str(submission.payload),
            'admin_url': f"/admin/builder/formsubmission/{submission.id}/",
        }
        
        success = True
        for email in admin_emails:
            result = self.send_notification(
                template_name='form_submission',
                channel='email',
                recipient=email,
                context=context
            )
            success = success and result
        
        return success
    
    def send_workspace_invitation(
        self,
        invitation,
        inviter_name: str
    ) -> bool:
        """Send workspace invitation email."""
        context = {
            'workspace_name': invitation.workspace.name,
            'inviter_name': inviter_name,
            'role': invitation.role,
            'invitation_url': f"/editor?invite_token={invitation.token}",
            'expiry_days': '7',
        }
        
        return self.send_notification(
            template_name='workspace_invitation',
            channel='email',
            recipient=invitation.email,
            context=context
        )
    
    def send_page_published_notification(
        self,
        page,
        user_name: str,
        webhook_urls: List[str]
    ) -> bool:
        """Send page published notification via webhooks."""
        context = {
            'page_title': page.title,
            'site_name': page.site.name,
            'page_url': f"/preview/{page.site.slug}{page.path}",
            'user_name': user_name,
            'published_at': page.published_at.strftime('%Y-%m-%d %H:%M:%S') if page.published_at else 'Now',
        }
        
        success = True
        for url in webhook_urls:
            result = self.send_notification(
                template_name='page_published',
                channel='webhook',
                recipient=url,
                context=context
            )
            success = success and result
        
        return success


# Global notification service instance
notification_service = NotificationService()
