"""
Form Builder Views

Provides API endpoints for form management, form rendering,
and public form submission with spam protection.
"""

import hashlib
import time
from django.db.models import Count, IntegerField, OuterRef, Subquery, Value
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.http import HttpResponse

from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from .experiments import record_conversion_from_assignments, resolve_public_page_context
from core.models import Site
from core.views import SitePermissionMixin
from forms.models import Form, FormSubmission
from forms.serializers import FormSerializer, FormSubmissionSerializer
from forms.services import trigger_webhooks


class FormViewSet(SitePermissionMixin, viewsets.ModelViewSet):
    """ViewSet for form builder forms."""
    serializer_class = FormSerializer

    def get_queryset(self):
        submission_count_subquery = (
            FormSubmission.objects.filter(
                site_id=OuterRef("site_id"),
                form_name=OuterRef("slug"),
            )
            .values("form_name")
            .annotate(total=Count("id"))
            .values("total")[:1]
        )
        qs = (
            Form.objects.select_related("site")
            .annotate(
                submission_count_annotated=Coalesce(
                    Subquery(submission_count_subquery, output_field=IntegerField()),
                    Value(0),
                )
            )
            .order_by("name")
        )
        site_id = self.request.query_params.get("site")
        if site_id:
            qs = qs.filter(site_id=site_id)
        return self.filter_by_site_permission(qs)

    @action(detail=True, methods=["post"])
    def activate(self, request, pk=None):
        """Activate a form for public submissions."""
        form = self.get_object()
        form.status = Form.STATUS_ACTIVE
        form.save(update_fields=["status", "updated_at"])
        return Response(self.get_serializer(form).data)

    @action(detail=True, methods=["post"])
    def deactivate(self, request, pk=None):
        """Deactivate a form."""
        form = self.get_object()
        form.status = Form.STATUS_DRAFT
        form.save(update_fields=["status", "updated_at"])
        return Response(self.get_serializer(form).data)

    @action(detail=True, methods=["post"])
    def archive(self, request, pk=None):
        """Archive a form."""
        form = self.get_object()
        form.status = Form.STATUS_ARCHIVED
        form.save(update_fields=["status", "updated_at"])
        return Response(self.get_serializer(form).data)

    @action(detail=True, methods=["get"])
    def submissions(self, request, pk=None):
        """Get submissions for this form."""
        form = self.get_object()
        submissions = FormSubmission.objects.filter(
            site=form.site,
            form_name=form.slug,
        ).order_by("-created_at")

        # Pagination
        page_size_raw = request.query_params.get("page_size", 50)
        page_raw = request.query_params.get("page", 1)
        try:
            page_size = int(page_size_raw)
            page = int(page_raw)
        except (TypeError, ValueError) as exc:
            raise ValidationError({"detail": "page and page_size must be integers."}) from exc
        if page < 1:
            raise ValidationError({"page": "page must be greater than or equal to 1."})
        if page_size < 1 or page_size > 200:
            raise ValidationError({"page_size": "page_size must be between 1 and 200."})

        start = (page - 1) * page_size
        end = start + page_size

        total = submissions.count()
        submissions = submissions[start:end]

        serializer = FormSubmissionSerializer(submissions, many=True, context={"request": request})
        return Response({
            "count": total,
            "page": page,
            "page_size": page_size,
            "results": serializer.data,
        })

    @action(detail=True, methods=["get"])
    def render_html(self, request, pk=None):
        """Render form as HTML for embedding."""
        form = self.get_object()
        html = generate_form_html(form, request)
        return HttpResponse(html, content_type="text/html")

    @action(detail=True, methods=["post"])
    def duplicate(self, request, pk=None):
        """Duplicate a form."""
        form = self.get_object()
        new_form = Form.objects.create(
            site=form.site,
            name=f"{form.name} (Copy)",
            slug=f"{form.slug}-copy-{int(time.time())}",
            description=form.description,
            status=Form.STATUS_DRAFT,
            fields=form.fields,
            submit_button_text=form.submit_button_text,
            success_message=form.success_message,
            redirect_url=form.redirect_url,
            notify_emails=form.notify_emails,
            enable_captcha=form.enable_captcha,
            honeypot_field=form.honeypot_field,
            form_class=form.form_class,
            settings=form.settings,
        )
        return Response(self.get_serializer(new_form).data, status=status.HTTP_201_CREATED)


class PublicFormView(APIView):
    """Public form rendering and submission."""
    permission_classes = [permissions.AllowAny]
    throttle_classes = []

    def get_throttles(self):
        from .throttles import PublicFormThrottle

        return [PublicFormThrottle()]

    def get(self, request, site_slug: str, form_slug: str):
        """Get form schema for rendering."""
        site = get_object_or_404(Site, slug=site_slug)
        form = get_object_or_404(Form, site=site, slug=form_slug, status=Form.STATUS_ACTIVE)
        
        return Response({
            "id": form.id,
            "name": form.name,
            "description": form.description,
            "fields": form.fields,
            "submit_button_text": form.submit_button_text,
            "enable_captcha": form.enable_captcha,
            "honeypot_field": form.honeypot_field,
            "form_class": form.form_class,
        })

    def post(self, request, site_slug: str, form_slug: str):
        """Submit a form."""
        site = get_object_or_404(Site, slug=site_slug)
        form = get_object_or_404(Form, site=site, slug=form_slug, status=Form.STATUS_ACTIVE)
        
        payload = request.data.get("payload", {})
        if not isinstance(payload, dict):
            return Response({"detail": "payload must be a JSON object."}, status=status.HTTP_400_BAD_REQUEST)
        raw_page_path = request.data.get("page_path") or request.META.get("HTTP_REFERER") or ""
        page, translation, locale, normalized_path = resolve_public_page_context(site, raw_page_path)
        
        # Spam protection: honeypot check
        honeypot_value = payload.pop(form.honeypot_field, None)
        if honeypot_value:
            # Bot detected - silently accept but don't save
            return Response({
                "success": True,
                "message": form.success_message,
            })
        
        # Validate required fields
        errors = {}
        for field in form.fields:
            field_name = field.get("name", "")
            field_required = field.get("required", False)
            field_type = field.get("type", "text")
            
            value = payload.get(field_name)
            
            if field_required and not value:
                errors[field_name] = f"{field.get('label', field_name)} is required."
                continue
            
            # Type-specific validation
            if value and field_type == "email":
                if "@" not in str(value) or "." not in str(value):
                    errors[field_name] = "Please enter a valid email address."
            
            # Custom validation rules
            validation = field.get("validation", {})
            if value and validation:
                min_length = validation.get("minLength")
                max_length = validation.get("maxLength")
                pattern = validation.get("pattern")
                
                if min_length and len(str(value)) < min_length:
                    errors[field_name] = f"Must be at least {min_length} characters."
                if max_length and len(str(value)) > max_length:
                    errors[field_name] = f"Must be at most {max_length} characters."
                if pattern:
                    import re
                    if not re.match(pattern, str(value)):
                        errors[field_name] = validation.get("patternMessage", "Invalid format.")
        
        if errors:
            return Response({"errors": errors}, status=status.HTTP_400_BAD_REQUEST)
        
        # Create submission
        submission = FormSubmission.objects.create(
            site=site,
            page=page,
            form_name=form.slug,
            payload=payload,
            status=FormSubmission.STATUS_NEW,
        )
        record_conversion_from_assignments(
            request,
            site=site,
            page=page,
            locale=translation.locale if translation else locale,
            form_name=form.slug,
            request_path=normalized_path,
            metadata={"source": "form_builder"},
        )
        
        # Trigger webhook
        trigger_webhooks(site, "form.submitted", {
            "form_id": form.id,
            "form_name": form.name,
            "form_slug": form.slug,
            "submission_id": submission.id,
            "payload": payload,
        })
        
        return Response({
            "success": True,
            "message": form.success_message,
            "redirect_url": form.redirect_url or None,
            "submission_id": submission.id,
        })


def generate_form_html(form: Form, request=None) -> str:
    """Generate embeddable HTML for a form."""
    base_url = request.build_absolute_uri("/") if request else ""
    submit_url = f"{base_url}api/public/forms/{form.site.slug}/{form.slug}/submit/"
    
    fields_html = []
    for field in form.fields:
        field_html = render_field_html(field)
        fields_html.append(field_html)
    
    # Honeypot field (hidden)
    honeypot_html = f'''
    <div style="position:absolute;left:-9999px;opacity:0;height:0;overflow:hidden;">
        <label for="{form.honeypot_field}">{form.honeypot_field}</label>
        <input type="text" name="{form.honeypot_field}" id="{form.honeypot_field}" tabindex="-1" autocomplete="off">
    </div>
    '''
    
    form_class = form.form_class or "wb-form"
    
    html = f'''
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{form.name}</title>
    <style>
        .wb-form {{ max-width: 500px; margin: 0 auto; font-family: system-ui, sans-serif; }}
        .wb-form-field {{ margin-bottom: 1rem; }}
        .wb-form-label {{ display: block; margin-bottom: 0.25rem; font-weight: 500; }}
        .wb-form-input {{ width: 100%; padding: 0.5rem; border: 1px solid #ccc; border-radius: 4px; font-size: 1rem; }}
        .wb-form-input:focus {{ outline: none; border-color: #3b82f6; box-shadow: 0 0 0 2px rgba(59,130,246,0.2); }}
        .wb-form-textarea {{ min-height: 100px; resize: vertical; }}
        .wb-form-submit {{ background: #3b82f6; color: white; padding: 0.75rem 1.5rem; border: none; border-radius: 4px; font-size: 1rem; cursor: pointer; }}
        .wb-form-submit:hover {{ background: #2563eb; }}
        .wb-form-required {{ color: #ef4444; }}
        .wb-form-help {{ font-size: 0.875rem; color: #666; margin-top: 0.25rem; }}
        .wb-form-error {{ color: #ef4444; font-size: 0.875rem; margin-top: 0.25rem; }}
        .wb-form-success {{ background: #10b981; color: white; padding: 1rem; border-radius: 4px; text-align: center; }}
    </style>
</head>
<body>
    <form class="{form_class}" id="wb-form-{form.slug}" action="{submit_url}" method="POST">
        {honeypot_html}
        {"".join(fields_html)}
        <div class="wb-form-field">
            <button type="submit" class="wb-form-submit">{form.submit_button_text}</button>
        </div>
    </form>
    <div id="wb-form-success-{form.slug}" class="wb-form-success" style="display:none;">
        {form.success_message}
    </div>
    <script>
        document.getElementById('wb-form-{form.slug}').addEventListener('submit', async function(e) {{
            e.preventDefault();
            const form = e.target;
            const formData = new FormData(form);
            const payload = {{}};
            formData.forEach((value, key) => {{ payload[key] = value; }});
            
            try {{
                const response = await fetch(form.action, {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ payload, page_path: window.location.pathname }})
                }});
                const data = await response.json();
                
                if (data.success) {{
                    form.style.display = 'none';
                    document.getElementById('wb-form-success-{form.slug}').style.display = 'block';
                    if (data.redirect_url) {{
                        setTimeout(() => {{ window.location.href = data.redirect_url; }}, 1500);
                    }}
                }} else if (data.errors) {{
                    // Show errors
                    Object.entries(data.errors).forEach(([field, message]) => {{
                        const input = form.querySelector('[name="' + field + '"]');
                        if (input) {{
                            let errorEl = input.parentNode.querySelector('.wb-form-error');
                            if (!errorEl) {{
                                errorEl = document.createElement('div');
                                errorEl.className = 'wb-form-error';
                                input.parentNode.appendChild(errorEl);
                            }}
                            errorEl.textContent = message;
                        }}
                    }});
                }}
            }} catch (err) {{
                console.error('Form submission error:', err);
            }}
        }});
    </script>
</body>
</html>
    '''
    return html


def render_field_html(field: dict) -> str:
    """Render a single form field as HTML."""
    field_type = field.get("type", "text")
    field_name = field.get("name", "")
    field_label = field.get("label", "")
    field_placeholder = field.get("placeholder", "")
    field_required = field.get("required", False)
    field_options = field.get("options", [])
    field_help = field.get("help_text", "")
    field_default = field.get("default_value", "")
    
    required_attr = 'required' if field_required else ''
    required_star = '<span class="wb-form-required">*</span>' if field_required else ''
    help_html = f'<div class="wb-form-help">{field_help}</div>' if field_help else ''
    
    if field_type == "textarea":
        input_html = f'''
        <textarea name="{field_name}" class="wb-form-input wb-form-textarea" 
            placeholder="{field_placeholder}" {required_attr}>{field_default}</textarea>
        '''
    elif field_type == "select":
        options_html = '<option value="">Select...</option>'
        for opt in field_options:
            selected = 'selected' if opt == field_default else ''
            options_html += f'<option value="{opt}" {selected}>{opt}</option>'
        input_html = f'''
        <select name="{field_name}" class="wb-form-input" {required_attr}>
            {options_html}
        </select>
        '''
    elif field_type == "radio":
        options_html = ''
        for opt in field_options:
            checked = 'checked' if opt == field_default else ''
            options_html += f'''
            <label style="display:block;margin:0.25rem 0;">
                <input type="radio" name="{field_name}" value="{opt}" {checked} {required_attr}> {opt}
            </label>
            '''
        input_html = options_html
    elif field_type == "checkbox":
        checked = 'checked' if field_default else ''
        input_html = f'''
        <label>
            <input type="checkbox" name="{field_name}" value="1" {checked}> {field_label}
        </label>
        '''
        # For checkbox, label is inline
        return f'''
        <div class="wb-form-field">
            {input_html}
            {help_html}
        </div>
        '''
    else:
        input_html = f'''
        <input type="{field_type}" name="{field_name}" class="wb-form-input" 
            placeholder="{field_placeholder}" value="{field_default}" {required_attr}>
        '''
    
    return f'''
    <div class="wb-form-field">
        <label class="wb-form-label">{field_label} {required_star}</label>
        {input_html}
        {help_html}
    </div>
    '''
