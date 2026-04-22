import hashlib
import secrets
from datetime import timedelta

from django.contrib.auth import authenticate, get_user_model, login, logout
from django.conf import settings
from django.core.mail import send_mail
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core import signing
from django.db import models
from django.http import Http404, HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.utils.decorators import method_decorator
from django.utils.crypto import constant_time_compare
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils import timezone
from django.utils.html import strip_tags
from django.contrib.syndication.views import Feed
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from rest_framework import permissions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from cms.page_schema import extract_page_summary, extract_render_cache, normalize_page_content

# Runtime helpers continue to live in this module during the app split.
from .commerce_runtime import calculate_cart_pricing, shipping_country_for, shipping_state_for  # noqa: F401
from core.models import (
    MFARecoveryCode,
    MFATOTPDevice,
    PersonalAPIKey,
    SecurityAuditLog,
    SecurityToken,
    SiteMembership,
    UserAccount,
    UserSecurityState,
    UserSession,
)
from blog.services import evaluate_comment_spam
from shared.auth.audit import log_security_event
from shared.auth.lockout import (
    clear_login_failures,
    login_backoff_wait_seconds,
    record_failed_login,
    user_is_locked,
)
from shared.auth.mfa import (
    build_totp_uri,
    generate_recovery_codes,
    generate_totp_secret,
    hash_recovery_code,
    verify_recovery_code,
    verify_totp,
)
from shared.auth.sessions import active_sessions_for_user, revoke_other_sessions, revoke_session, start_user_session
from shared.auth.social import registry as social_provider_registry
from shared.auth.tokens import (
    consume_security_token,
    issue_security_token,
    revoke_all_refresh_tokens,
    revoke_refresh_token,
    rotate_refresh_token,
)
from shared.contracts.sanitize import sanitize_json_payload, sanitize_text
from shared.policies.access import SitePermission


class SiteObjectPermission(permissions.BasePermission):
    """Enforce view/edit access for site-scoped detail objects."""

    message = "You don't have permission to access this site."

    def has_object_permission(self, request, view, obj):
        if not hasattr(view, "get_site_for_object"):
            return True
        site = view.get_site_for_object(obj)
        if site is None:
            return False
        required_permission = (
            getattr(view, "site_read_permission", SitePermission.VIEW)
            if request.method in permissions.SAFE_METHODS
            else getattr(view, "site_write_permission", SitePermission.EDIT)
        )
        from shared.policies.access import has_site_permission

        return has_site_permission(request.user, site, required_permission)


class SitePermissionMixin:
    """Mixin to filter querysets by user's workspace permissions."""

    site_lookup_field = "site"
    site_read_permission = SitePermission.VIEW
    site_write_permission = SitePermission.EDIT
    permission_classes = [permissions.IsAuthenticated, SiteObjectPermission]

    def _api_key_for_request(self):
        key = getattr(self.request, "auth_api_key", None)
        if key is not None:
            return key
        auth_obj = getattr(self.request, "auth", None)
        return auth_obj if isinstance(auth_obj, PersonalAPIKey) else None

    def _assert_scope(self, *, write: bool) -> None:
        key = self._api_key_for_request()
        if key is None:
            return
        scopes = set(key.scopes or [])
        read_scopes = {"sites:read", "content:read", "commerce:read", "analytics:read", "forms:read", "domains:read"}
        write_scopes = {"sites:write", "content:write", "commerce:write", "forms:write", "domains:write", "webhooks:write"}
        if write:
            if not (scopes & write_scopes):
                raise PermissionDenied("API key scope does not allow write access.")
        else:
            if not (scopes & (read_scopes | write_scopes)):
                raise PermissionDenied("API key scope does not allow read access.")

    def _site_from_candidate(self, candidate):
        if candidate is None:
            return None
        if isinstance(candidate, dict):
            for key in ("site", "page", "post", "product", "zone", "keyword", "review", "form"):
                if key in candidate:
                    site = self._site_from_candidate(candidate[key])
                    if site is not None:
                        return site
            return None
        if isinstance(candidate, Site):
            return candidate
        for attr in ("site", "page", "post", "product", "zone", "keyword", "review", "form"):
            related = getattr(candidate, attr, None)
            if related is None:
                continue
            site = self._site_from_candidate(related)
            if site is not None:
                return site
        return None

    def get_site_for_object(self, obj):
        return self._site_from_candidate(obj)

    def get_site_from_serializer(self, serializer):
        site = self._site_from_candidate(getattr(serializer, "validated_data", {}))
        if site is not None:
            return site
        return self._site_from_candidate(getattr(serializer, "instance", None))

    def filter_by_site_permission(self, queryset):
        """Filter queryset to only include items from sites the user can access."""
        from .workspace_views import filter_sites_by_permission

        self._assert_scope(write=False)
        user = self.request.user
        if user.is_superuser:
            return queryset
        if not user.is_authenticated:
            return queryset.none()
        # Get accessible site IDs
        accessible_sites = filter_sites_by_permission(user, Site.objects.all())
        return queryset.filter(**{f"{self.site_lookup_field}__in": accessible_sites}).distinct()

    def get_site_from_request(self, *, key: str = "site", source: str = "query", require_edit: bool = False):
        self._assert_scope(write=require_edit)
        if source == "query":
            raw_site_id = self.request.query_params.get(key)
        else:
            raw_site_id = self.request.data.get(key)
        if not raw_site_id:
            raise ValidationError({key: "This field is required."})
        try:
            site_id = int(raw_site_id)
        except (TypeError, ValueError) as exc:
            raise ValidationError({key: "A valid site id is required."}) from exc
        site = get_object_or_404(Site.objects.select_related("workspace"), pk=site_id)
        if require_edit:
            self.check_site_edit_permission(site)
        else:
            from shared.policies.access import has_site_permission

            if not has_site_permission(self.request.user, site, self.site_read_permission):
                raise PermissionDenied("You don't have permission to access this site.")
        return site

    def check_site_edit_permission(self, site):
        """Check if user can edit content on this site."""
        self._assert_scope(write=True)
        from shared.policies.access import has_site_permission

        if not has_site_permission(self.request.user, site, self.site_write_permission):
            raise PermissionDenied("You don't have permission to edit this site.")

    def check_site_manage_permission(self, site):
        from shared.policies.access import has_site_permission

        return has_site_permission(self.request.user, site, SitePermission.MANAGE)

    def perform_create(self, serializer):
        site = self.get_site_from_serializer(serializer)
        if site is None:
            raise ValidationError({"site": "A valid site is required."})
        self.check_site_edit_permission(site)
        return serializer.save()

    def perform_update(self, serializer):
        site = self.get_site_from_serializer(serializer)
        if site is None:
            raise ValidationError({"site": "A valid site is required."})
        self.check_site_edit_permission(site)
        return serializer.save()


from .models import (
    AssetUsageReference,
    BlogAuthor,
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
    Page,
    PageExperiment,
    PageReview,
    PageReviewComment,
    PageTranslation,
    PageRevision,
    Post,
    PostCategory,
    PostTag,
    PreviewToken,
    PublishSnapshot,
    Product,
    ProductCategory,
    ProductVariant,
    ReusableSection,
    ShippingRate,
    ShippingZone,
    KeywordRankEntry,
    SearchConsoleCredential,
    SEOAnalytics,
    SEOAudit,
    SEOSettings,
    Site,
    SiteLocale,
    SiteShell,
    TaxRate,
    ThemeTemplate,
    TrackedKeyword,
    URLRedirect,
    Webhook,
    Workspace,
    WorkspaceInvitation,
    WorkspaceMembership,
)
from .experiments import (
    apply_variant_to_page_payload,
    evaluate_page_experiments,
    persist_experiment_cookies,
    record_conversion_from_assignments,
    resolve_public_page_context,
)
from .localization import (
    build_translation_payload,
    clone_page_translation_content,
    localized_preview_url,
    normalize_locale_code,
    normalize_translation_path,
    select_best_locale,
    sync_site_localization_settings,
)
from .mirror_import import import_mirrored_site
from .jobs import queue_search_index
from .serializers import (
    AssetUsageReferenceSerializer,
    APIKeyRevokeSerializer,
    APIKeyCreateSerializer,
    AuthChangePasswordSerializer,
    AuthBootstrapSerializer,
    AuthLoginSerializer,
    AuthMFABackupCodeSerializer,
    AuthMFAChallengeVerifySerializer,
    AuthMFATOTPSetupSerializer,
    AuthMFATOTPVerifySerializer,
    AuthRegisterSerializer,
    AuthSessionRevokeSerializer,
    AuthSocialLoginSerializer,
    AuthTokenRefreshSerializer,
    AuthTokenRevokeSerializer,
    BlogAuthorSerializer,
    BlockTemplateSerializer,
    BuilderSaveSerializer,
    CartSerializer,
    CommentSerializer,
    DomainAvailabilitySerializer,
    DomainContactSerializer,
    DomainSerializer,
    DiscountCodeSerializer,
    FormSubmissionSerializer,
    MediaAssetSerializer,
    MediaFolderSerializer,
    NavigationMenuSerializer,
    OrderSerializer,
    PageRevisionSerializer,
    PageExperimentSerializer,
    PageReviewCommentSerializer,
    PageReviewSerializer,
    PageSerializer,
    PageTranslationSerializer,
    PaymentIntentSerializer,
    PublicCommentSubmissionSerializer,
    PublicCartAddSerializer,
    PublicCartItemUpdateSerializer,
    PublicCheckoutSerializer,
    PublicFormSubmissionSerializer,
    PostCategorySerializer,
    PostSerializer,
    PostTagSerializer,
    PreviewTokenSerializer,
    PublishSnapshotSerializer,
    ProductCategorySerializer,
    ProductSerializer,
    ProductVariantSerializer,
    PublicCartPricingSerializer,
    KeywordRankEntrySerializer,
    SearchConsoleCredentialSerializer,
    SEOAnalyticsSerializer,
    SEOAuditSerializer,
    SEOSettingsSerializer,
    ReusableSectionSerializer,
    ShippingRateSerializer,
    ShippingZoneSerializer,
    SiteSerializer,
    SiteLocaleSerializer,
    SiteMembershipSerializer,
    SiteMembershipUpsertSerializer,
    SiteShellSerializer,
    SiteMirrorImportSerializer,
    TaxRateSerializer,
    TrackedKeywordSerializer,
    URLRedirectSerializer,
    WebhookSerializer,
    WorkspaceSerializer,
    WorkspaceMembershipSerializer,
    WorkspaceInvitationSerializer,
    InviteMemberSerializer,
    EmailVerificationConfirmSerializer,
    EmailVerificationRequestSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    ChangeMemberRoleSerializer,
    CollaboratorUserSerializer,
    UserActivitySerializer,
    ThemeTemplateSerializer,
)
from .services import (
    BASE_BLOCK_CSS,
    build_page_payload,
    build_theme_css,
    create_order_from_cart,
    create_revision,
    ensure_seed_data,
    ensure_variant_inventory,
    get_or_create_cart,
    normalize_page_path,
    ensure_unique_page_path,
    preview_url_for_page,
    preview_url_for_page_translation,
    preview_url_for_post,
    preview_url_for_product,
    recalculate_cart,
    resolve_variant,
    sync_cart_item,
    sync_homepage_state,
    starter_kits,
    trigger_webhooks,
)
from shared.search.service import search_index


User = get_user_model()


def _snapshot_payload_for_content(instance) -> dict:
    payload: dict[str, object] = {
        "id": getattr(instance, "id", None),
        "updated_at": getattr(instance, "updated_at", None).isoformat() if getattr(instance, "updated_at", None) else None,
    }
    for field in ("title", "slug", "path", "status", "seo", "page_settings", "builder_data", "html", "css", "js"):
        if hasattr(instance, field):
            payload[field] = getattr(instance, field)
    return payload


def create_publish_snapshot(
    *,
    site: Site,
    target_type: str,
    target_id: int,
    instance,
    actor=None,
    revision_label: str = "",
    metadata: dict | None = None,
) -> PublishSnapshot:
    return PublishSnapshot.objects.create(
        site=site,
        target_type=target_type,
        target_id=target_id,
        revision_label=revision_label,
        snapshot=_snapshot_payload_for_content(instance),
        actor=actor if actor and getattr(actor, "is_authenticated", False) else None,
        metadata=metadata or {},
    )


class DashboardSummaryView(APIView):
    def get(self, request):
        from .workspace_views import filter_sites_by_permission

        ensure_seed_data()
        accessible_sites = filter_sites_by_permission(request.user, Site.objects.all())
        site_ids = accessible_sites.values_list("id", flat=True)
        page_count = Page.objects.filter(site_id__in=site_ids).count()
        published_count = Page.objects.filter(site_id__in=site_ids, status=Page.STATUS_PUBLISHED).count()
        data = {
            "sites": accessible_sites.count(),
            "pages": page_count,
            "published_pages": published_count,
            "draft_pages": page_count - published_count,
            "posts": Post.objects.filter(site_id__in=site_ids).count(),
            "published_posts": Post.objects.filter(site_id__in=site_ids, status=Post.STATUS_PUBLISHED).count(),
            "draft_posts": Post.objects.filter(site_id__in=site_ids, status=Post.STATUS_DRAFT).count(),
            "media_assets": MediaAsset.objects.filter(site_id__in=site_ids).count(),
            "comments": Comment.objects.filter(post__site_id__in=site_ids).count(),
            "approved_comments": Comment.objects.filter(post__site_id__in=site_ids, is_approved=True).count(),
            "submissions": FormSubmission.objects.filter(site_id__in=site_ids).count(),
            "products": Product.objects.filter(site_id__in=site_ids).count(),
            "published_products": Product.objects.filter(site_id__in=site_ids, status=Product.STATUS_PUBLISHED).count(),
            "orders": Order.objects.filter(site_id__in=site_ids).count(),
            "open_carts": Cart.objects.filter(site_id__in=site_ids, status=Cart.STATUS_OPEN).count(),
            "starter_kits": starter_kits(),
        }
        return Response(data)


def _truncate_text(value: str, limit: int = 160) -> str:
    compact = " ".join(strip_tags(value or "").split())
    if len(compact) <= limit:
        return compact
    return f"{compact[: limit - 1].rstrip()}..."


def _editor_page_url(page: Page) -> str:
    return f"/editor?site={page.site_id}&page={page.id}"


class WorkspaceSearchView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        from .workspace_views import filter_sites_by_permission

        ensure_seed_data()

        query = (request.query_params.get("q") or "").strip()
        if len(query) < 2:
            return Response({"results": [], "query": query, "backend": "none"})

        site_id = request.query_params.get("site")
        try:
            limit = max(1, min(int(request.query_params.get("limit", 8)), 20))
        except (TypeError, ValueError):
            limit = 8

        accessible_sites = filter_sites_by_permission(request.user, Site.objects.all()).order_by("name")
        if site_id:
            accessible_sites = accessible_sites.filter(pk=site_id)

        site_map = {site.id: site for site in accessible_sites}
        results: list[dict[str, object]] = []
        backend_name = "orm"

        if search_index.is_enabled():
            results = self._search_meilisearch(query, site_map, limit, request)
            if results:
                backend_name = "meilisearch"

        if not results:
            results = self._search_database(query, site_map, limit, request)

        return Response({"results": results[:limit], "query": query, "backend": backend_name})

    def _search_meilisearch(self, query: str, site_map: dict[int, Site], limit: int, request) -> list[dict[str, object]]:
        search_index.ensure_indexes()
        raw_results = search_index.search_all(query=query, site_id=None, limit_per_index=max(1, min(limit, 5)))
        if not raw_results:
            return []

        ids_by_type: dict[str, list[int]] = {
            "page": [],
            "post": [],
            "product": [],
            "media": [],
        }

        for index_name, payload in raw_results.items():
            for hit in payload.get("hits", []):
                doc_id = str(hit.get("id", ""))
                try:
                    item_id = int(doc_id.split("_", 1)[1])
                except (IndexError, ValueError):
                    continue
                try:
                    site_id = int(hit.get("site_id"))
                except (TypeError, ValueError):
                    continue
                if site_id not in site_map:
                    continue
                item_type = str(hit.get("type", index_name.rstrip("s")))
                if item_type in ids_by_type:
                    ids_by_type[item_type].append(item_id)

        results: list[dict[str, object]] = []
        results.extend(self._serialize_pages_by_id(ids_by_type["page"], site_map, request))
        results.extend(self._serialize_posts_by_id(ids_by_type["post"], site_map))
        results.extend(self._serialize_products_by_id(ids_by_type["product"], site_map))
        results.extend(self._serialize_media_by_id(ids_by_type["media"], site_map, request))
        return results[:limit]

    def _search_database(self, query: str, site_map: dict[int, Site], limit: int, request) -> list[dict[str, object]]:
        site_ids = list(site_map.keys())
        if not site_ids:
            return []

        pages = (
            Page.objects.select_related("site")
            .filter(site_id__in=site_ids)
            .filter(
                models.Q(title__icontains=query)
                | models.Q(slug__icontains=query)
                | models.Q(path__icontains=query)
                | models.Q(html__icontains=query)
            )
            .order_by("-updated_at")[:limit]
        )
        posts = (
            Post.objects.select_related("site")
            .filter(site_id__in=site_ids)
            .filter(
                models.Q(title__icontains=query)
                | models.Q(slug__icontains=query)
                | models.Q(excerpt__icontains=query)
                | models.Q(body_html__icontains=query)
            )
            .order_by("-updated_at")[:limit]
        )
        products = (
            Product.objects.select_related("site")
            .filter(site_id__in=site_ids)
            .filter(
                models.Q(title__icontains=query)
                | models.Q(slug__icontains=query)
                | models.Q(excerpt__icontains=query)
                | models.Q(description_html__icontains=query)
            )
            .order_by("-updated_at")[:limit]
        )
        media_assets = (
            MediaAsset.objects.select_related("site")
            .filter(site_id__in=site_ids)
            .filter(
                models.Q(title__icontains=query)
                | models.Q(alt_text__icontains=query)
                | models.Q(caption__icontains=query)
            )
            .order_by("-updated_at")[:limit]
        )

        results: list[dict[str, object]] = []
        results.extend(self._serialize_page(page) for page in pages)
        results.extend(self._serialize_post(post) for post in posts)
        results.extend(self._serialize_product(product) for product in products)
        results.extend(self._serialize_media(asset, request) for asset in media_assets)

        results.sort(key=lambda item: str(item.get("updated_at", "")), reverse=True)
        return results[:limit]

    def _serialize_pages_by_id(self, page_ids: list[int], site_map: dict[int, Site], request) -> list[dict[str, object]]:
        if not page_ids:
            return []
        pages = {
            page.id: page
            for page in Page.objects.select_related("site").filter(id__in=page_ids, site_id__in=site_map.keys())
        }
        return [self._serialize_page(pages[page_id]) for page_id in page_ids if page_id in pages]

    def _serialize_posts_by_id(self, post_ids: list[int], site_map: dict[int, Site]) -> list[dict[str, object]]:
        if not post_ids:
            return []
        posts = {
            post.id: post
            for post in Post.objects.select_related("site").filter(id__in=post_ids, site_id__in=site_map.keys())
        }
        return [self._serialize_post(posts[post_id]) for post_id in post_ids if post_id in posts]

    def _serialize_products_by_id(self, product_ids: list[int], site_map: dict[int, Site]) -> list[dict[str, object]]:
        if not product_ids:
            return []
        products = {
            product.id: product
            for product in Product.objects.select_related("site").filter(id__in=product_ids, site_id__in=site_map.keys())
        }
        return [self._serialize_product(products[product_id]) for product_id in product_ids if product_id in products]

    def _serialize_media_by_id(self, media_ids: list[int], site_map: dict[int, Site], request) -> list[dict[str, object]]:
        if not media_ids:
            return []
        assets = {
            asset.id: asset
            for asset in MediaAsset.objects.select_related("site").filter(id__in=media_ids, site_id__in=site_map.keys())
        }
        return [self._serialize_media(assets[media_id], request) for media_id in media_ids if media_id in assets]

    def _serialize_page(self, page: Page) -> dict[str, object]:
        summary = extract_page_summary(page.builder_data) or page.seo.get("meta_description", "") or page.path
        return {
            "id": f"page_{page.id}",
            "type": "page",
            "title": page.title,
            "excerpt": _truncate_text(summary),
            "url": _editor_page_url(page),
            "preview_url": preview_url_for_page(page),
            "site_id": page.site_id,
            "site_name": page.site.name,
            "site_slug": page.site.slug,
            "status": page.status,
            "updated_at": page.updated_at.isoformat(),
        }

    def _serialize_post(self, post: Post) -> dict[str, object]:
        return {
            "id": f"post_{post.id}",
            "type": "post",
            "title": post.title,
            "excerpt": _truncate_text(post.excerpt or post.body_html),
            "url": f"{preview_url_for_post(post)}",
            "site_id": post.site_id,
            "site_name": post.site.name,
            "site_slug": post.site.slug,
            "status": post.status,
            "updated_at": post.updated_at.isoformat(),
        }

    def _serialize_product(self, product: Product) -> dict[str, object]:
        return {
            "id": f"product_{product.id}",
            "type": "product",
            "title": product.title,
            "excerpt": _truncate_text(product.excerpt or product.description_html),
            "url": f"{preview_url_for_product(product)}",
            "site_id": product.site_id,
            "site_name": product.site.name,
            "site_slug": product.site.slug,
            "status": product.status,
            "updated_at": product.updated_at.isoformat(),
        }

    def _serialize_media(self, asset: MediaAsset, request) -> dict[str, object]:
        file_url = request.build_absolute_uri(asset.file.url) if asset.file else ""
        return {
            "id": f"media_{asset.id}",
            "type": "media",
            "title": asset.title,
            "excerpt": _truncate_text(asset.caption or asset.alt_text or asset.kind),
            "url": file_url,
            "site_id": asset.site_id,
            "site_name": asset.site.name,
            "site_slug": asset.site.slug,
            "status": asset.kind,
            "updated_at": asset.updated_at.isoformat(),
        }


@method_decorator(ensure_csrf_cookie, name="dispatch")
class AuthStatusView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        user = request.user if request.user.is_authenticated else None
        email_verified = False
        mfa_enabled = False
        account_status = None
        impersonating = False
        if user:
            account, _ = UserAccount.objects.get_or_create(
                user=user,
                defaults={"email": (user.email or f"user-{user.pk}@local.invalid").strip().lower()},
            )
            email_verified = bool(account.email_verified_at)
            mfa_enabled = bool(account.mfa_enabled)
            account_status = account.status
            impersonating = bool(request.session.get("impersonator_user_id"))
        return Response(
            {
                "authenticated": bool(user),
                "has_users": User.objects.exists(),
                "user": (
                    {
                        "id": user.id,
                        "username": user.username,
                        "email": user.email,
                        "is_superuser": user.is_superuser,
                        "email_verified": email_verified,
                        "mfa_enabled": mfa_enabled,
                        "account_status": account_status,
                        "impersonating": impersonating,
                    }
                    if user
                    else None
                ),
            }
        )


@method_decorator(csrf_protect, name="dispatch")
class AuthBootstrapView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = []

    def get_throttles(self):
        from .throttles import AuthBootstrapThrottle

        return [AuthBootstrapThrottle()]

    def post(self, request):
        from django.db import transaction, IntegrityError

        if not getattr(settings, "AUTH_BOOTSTRAP_ENABLED", settings.DEBUG):
            return Response(
                {"detail": "Bootstrap is disabled in this environment."},
                status=status.HTTP_403_FORBIDDEN,
            )

        bootstrap_token = getattr(settings, "AUTH_BOOTSTRAP_TOKEN", "")
        if bootstrap_token:
            provided_token = (
                request.headers.get("X-Bootstrap-Token")
                or request.data.get("bootstrap_token", "")
            )
            if not constant_time_compare(str(provided_token), bootstrap_token):
                log_security_event(
                    "auth.bootstrap.failed",
                    request=request,
                    actor=request.user if request.user.is_authenticated else None,
                    success=False,
                    metadata={"reason": "invalid_bootstrap_token"},
                )
                return Response(
                    {"detail": "Invalid bootstrap token."},
                    status=status.HTTP_403_FORBIDDEN,
                )

        serializer = AuthBootstrapSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            with transaction.atomic():
                # Use select_for_update to lock and prevent race condition
                # Check inside transaction to ensure atomicity
                if User.objects.select_for_update().exists():
                    log_security_event(
                        "auth.bootstrap.failed",
                        request=request,
                        success=False,
                        metadata={"reason": "bootstrap_already_completed"},
                    )
                    return Response(
                        {"detail": "Bootstrap is disabled after the first user is created."},
                        status=status.HTTP_400_BAD_REQUEST
                    )

                user = User.objects.create_superuser(
                    username=serializer.validated_data["username"],
                    email=serializer.validated_data.get("email", ""),
                    password=serializer.validated_data["password"],
                )
        except IntegrityError:
            log_security_event(
                "auth.bootstrap.failed",
                request=request,
                success=False,
                metadata={"reason": "integrity_error"},
            )
            return Response(
                {"detail": "Bootstrap is disabled after the first user is created."},
                status=status.HTTP_400_BAD_REQUEST
            )

        login(request, user)
        start_user_session(request=request, user=user, auth_method=UserSession.AUTH_SESSION)
        log_security_event(
            "auth.bootstrap.success",
            request=request,
            actor=user,
            target_type="user",
            target_id=str(user.pk),
        )
        return Response(
            {
                "authenticated": True,
                "has_users": True,
                "user": {
                    "id": user.id,
                    "username": user.username,
                    "email": user.email,
                    "is_superuser": user.is_superuser,
                },
            },
            status=status.HTTP_201_CREATED,
        )


def _ensure_user_account(user):
    account, _ = UserAccount.objects.get_or_create(
        user=user,
        defaults={
            "email": (user.email or f"user-{user.pk}@local.invalid").strip().lower(),
            "display_name": (user.get_full_name() or user.username).strip()[:160],
            "status": UserAccount.STATUS_ACTIVE if user.is_active else UserAccount.STATUS_SUSPENDED,
        },
    )
    return account


def _build_access_token_for_user(user) -> tuple[str, int]:
    state, _ = UserSecurityState.objects.get_or_create(user=user)
    now_ts = int(timezone.now().timestamp())
    ttl = int(getattr(settings, "AUTH_ACCESS_TOKEN_TTL_SECONDS", 900))
    access_token = signing.dumps(
        {
            "sub": user.pk,
            "iat": now_ts,
            "exp": now_ts + ttl,
            "ver": int(state.access_token_version or 1),
        },
        salt="wb.auth.access.v1",
        compress=True,
    )
    return access_token, ttl


def _auth_user_payload(user, *, request, include_security: bool = True) -> dict[str, object]:
    account = _ensure_user_account(user)
    payload: dict[str, object] = {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "is_superuser": user.is_superuser,
    }
    if include_security:
        payload.update(
            {
                "email_verified": bool(account.email_verified_at),
                "mfa_enabled": bool(account.mfa_enabled),
                "account_status": account.status,
                "impersonating": bool(request.session.get("impersonator_user_id")),
            }
        )
    return payload


@method_decorator(csrf_protect, name="dispatch")
class AuthRegisterView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = []

    def get_throttles(self):
        from .throttles import AuthSessionThrottle

        return [AuthSessionThrottle()]

    def post(self, request):
        serializer = AuthRegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"].strip().lower()
        username = serializer.validated_data.get("username", "").strip()
        if not username:
            base = email.split("@")[0] or "user"
            username = base
            suffix = 2
            while User.objects.filter(username=username).exists():
                username = f"{base}{suffix}"
                suffix += 1
        if User.objects.filter(email__iexact=email).exists():
            return Response({"detail": "A user with this email already exists."}, status=status.HTTP_409_CONFLICT)
        user = User.objects.create_user(
            username=username,
            email=email,
            password=serializer.validated_data["password"],
            is_active=True,
        )
        account = _ensure_user_account(user)
        account.status = UserAccount.STATUS_ACTIVE
        if serializer.validated_data.get("display_name"):
            account.display_name = serializer.validated_data["display_name"].strip()[:160]
        if serializer.validated_data.get("avatar_url"):
            account.avatar_url = serializer.validated_data["avatar_url"]
        if serializer.validated_data.get("profile_bio"):
            account.profile_bio = serializer.validated_data["profile_bio"]
        if serializer.validated_data.get("accept_terms"):
            account.terms_accepted_at = timezone.now()
            account.privacy_accepted_at = timezone.now()
            account.data_processing_consent_at = timezone.now()
        account.marketing_opt_in = bool(serializer.validated_data.get("marketing_opt_in", False))
        account.save()

        login(request, user)
        start_user_session(request=request, user=user, auth_method=UserSession.AUTH_SESSION)
        log_security_event(
            "auth.register",
            request=request,
            actor=user,
            target_type="user",
            target_id=str(user.pk),
            metadata={"email": email},
        )
        return Response(
            {
                "authenticated": True,
                "has_users": True,
                "user": _auth_user_payload(user, request=request),
            },
            status=status.HTTP_201_CREATED,
        )


@method_decorator(csrf_protect, name="dispatch")
class AuthLoginView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = []

    def get_throttles(self):
        from .throttles import AuthLoginThrottle

        return [AuthLoginThrottle()]

    def post(self, request):
        serializer = AuthLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        identifier = serializer.validated_data["identifier"]
        client_ip = (request.META.get("HTTP_X_FORWARDED_FOR") or request.META.get("REMOTE_ADDR") or "").split(",")[0].strip()

        wait_seconds = login_backoff_wait_seconds(identifier, client_ip)
        if wait_seconds > 0:
            response = Response(
                {"detail": "Too many authentication attempts. Please try again shortly."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
            response["Retry-After"] = str(wait_seconds)
            return response

        candidate_user = User.objects.filter(models.Q(username__iexact=identifier) | models.Q(email__iexact=identifier)).first()
        username = candidate_user.username if candidate_user else identifier
        if candidate_user is not None:
            account = _ensure_user_account(candidate_user)
            if account.status in {UserAccount.STATUS_DELETED, UserAccount.STATUS_SUSPENDED}:
                return Response({"detail": "Account is disabled."}, status=status.HTTP_403_FORBIDDEN)
            locked, retry_after = user_is_locked(candidate_user)
            if locked:
                log_security_event(
                    "auth.login.locked",
                    request=request,
                    actor=candidate_user,
                    target_type="user",
                    target_id=str(candidate_user.pk),
                    success=False,
                    metadata={"retry_after": retry_after},
                )
                response = Response(
                    {"detail": "Account temporarily locked due to repeated failed attempts."},
                    status=status.HTTP_423_LOCKED,
                )
                response["Retry-After"] = str(retry_after)
                return response

        user = authenticate(
            request,
            username=username,
            password=serializer.validated_data["password"],
        )
        if not user:
            locked, retry_after = record_failed_login(username=identifier, ip=client_ip, user=candidate_user)
            log_security_event(
                "auth.login.failed",
                request=request,
                actor=candidate_user,
                target_type="user",
                target_id=str(candidate_user.pk) if candidate_user else "",
                success=False,
                metadata={"locked": locked, "retry_after": retry_after},
            )
            if locked:
                response = Response(
                    {"detail": "Account temporarily locked due to repeated failed attempts."},
                    status=status.HTTP_423_LOCKED,
                )
                response["Retry-After"] = str(retry_after)
                return response
            return Response({"detail": "Invalid username or password."}, status=status.HTTP_400_BAD_REQUEST)

        account = _ensure_user_account(user)
        if account.status in {UserAccount.STATUS_DELETED, UserAccount.STATUS_SUSPENDED}:
            return Response({"detail": "Account is disabled."}, status=status.HTTP_403_FORBIDDEN)

        clear_login_failures(username=identifier, ip=client_ip, user=user)

        if account.mfa_enabled:
            challenge_token, _ = issue_security_token(
                user=user,
                purpose=SecurityToken.PURPOSE_MFA_CHALLENGE,
                ttl_seconds=getattr(settings, "AUTH_MFA_CHALLENGE_TTL_SECONDS", 300),
                request=request,
                metadata={"identifier": identifier},
            )
            log_security_event(
                "auth.login.mfa_challenge",
                request=request,
                actor=user,
                target_type="user",
                target_id=str(user.pk),
            )
            return Response(
                {
                    "mfa_required": True,
                    "challenge_token": challenge_token,
                    "methods": ["totp", "recovery_code"],
                },
                status=status.HTTP_202_ACCEPTED,
            )

        login(request, user)
        request.session.set_expiry(getattr(settings, "SESSION_COOKIE_AGE", 1209600))
        start_user_session(request=request, user=user, auth_method=UserSession.AUTH_SESSION)
        log_security_event(
            "auth.login.success",
            request=request,
            actor=user,
            target_type="user",
            target_id=str(user.pk),
        )
        return Response(
            {
                "authenticated": True,
                "has_users": True,
                "user": _auth_user_payload(user, request=request),
            }
        )


@method_decorator(csrf_protect, name="dispatch")
class AuthLogoutView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        actor = request.user if request.user.is_authenticated else None
        if actor is not None:
            revoke_all_refresh_tokens(actor)
            active_session_id = request.session.get("active_user_session_id")
            if active_session_id:
                revoke_session(user=actor, session_id=int(active_session_id))
                request.session.pop("active_user_session_id", None)
        logout(request)
        log_security_event(
            "auth.logout",
            request=request,
            actor=actor,
            target_type="user",
            target_id=str(actor.pk) if actor else "",
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class HealthCheckView(APIView):
    """Production health check endpoint for orchestration/load balancers."""
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        from django.db import connection

        health = {"status": "ok", "checks": {}}

        # Database connectivity check
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
            health["checks"]["database"] = "ok"
        except Exception as e:
            health["status"] = "degraded"
            health["checks"]["database"] = f"error: {type(e).__name__}"

        # Return 503 if critical checks fail
        if health["checks"].get("database") != "ok":
            return Response(health, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        return Response(health)


class LivenessCheckView(APIView):
    """Liveness endpoint: confirms the process is serving HTTP."""

    permission_classes = [permissions.AllowAny]

    def get(self, request):
        return Response({"status": "ok"})


class ReadinessCheckView(APIView):
    """Readiness endpoint: confirms dependencies are reachable."""

    permission_classes = [permissions.AllowAny]

    def get(self, request):
        from shared.cache.bootstrap import cache_is_healthy
        from shared.db.bootstrap import database_is_healthy

        checks = {
            "database": "ok" if database_is_healthy() else "error",
            "cache": "ok" if cache_is_healthy() else "error",
        }
        status_value = "ok" if all(value == "ok" for value in checks.values()) else "degraded"
        payload = {"status": status_value, "checks": checks}
        if status_value != "ok":
            return Response(payload, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response(payload)


class VersionView(APIView):
    """Version/build endpoint for operators and runtime debugging."""

    permission_classes = [permissions.AllowAny]

    def get(self, request):
        import os

        from django import get_version as django_get_version

        return Response(
            {
                "version": (os.environ.get("APP_VERSION") or "").strip() or None,
                "commit": (os.environ.get("GIT_SHA") or os.environ.get("COMMIT_SHA") or "").strip() or None,
                "environment": (os.environ.get("APP_ENV") or "").strip().lower() or None,
                "django": django_get_version(),
            }
        )


class MetricsView(APIView):
    """Basic metrics endpoint for monitoring."""
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        if not settings.DEBUG:
            metrics_token = getattr(settings, "METRICS_AUTH_TOKEN", "")
            if not metrics_token:
                raise Http404("Not available")
            provided_token = request.headers.get("X-Metrics-Token") or ""
            if not provided_token and getattr(settings, "METRICS_ALLOW_QUERY_TOKEN", False):
                provided_token = request.query_params.get("token", "")
            if not provided_token or not secrets.compare_digest(str(provided_token), metrics_token):
                raise Http404("Not available")

        from django.db import connection
        from .models import Job

        metrics = {}

        # Basic application metrics
        try:
            metrics["users_total"] = User.objects.count()
            metrics["sites_total"] = Site.objects.count()
            metrics["pages_total"] = Page.objects.count()
            metrics["orders_total"] = Order.objects.count()
        except Exception:
            pass

        # Job queue metrics
        try:
            metrics["jobs_pending"] = Job.objects.filter(status=Job.STATUS_PENDING).count()
            metrics["jobs_running"] = Job.objects.filter(status=Job.STATUS_RUNNING).count()
            metrics["jobs_failed"] = Job.objects.filter(status=Job.STATUS_FAILED).count()
        except Exception:
            pass

        # Database connection info
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
            metrics["database_connected"] = True
        except Exception:
            metrics["database_connected"] = False

        response = Response(metrics)
        response["Cache-Control"] = "no-store"
        return response


class AuthMagicLoginView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = []

    def get_throttles(self):
        from .throttles import AuthMagicLoginThrottle

        return [AuthMagicLoginThrottle()]

    def get(self, request):
        if not getattr(settings, "AUTH_MAGIC_LOGIN_ENABLED", settings.DEBUG):
            raise Http404("Not available")

        username = (request.query_params.get("username") or "").strip()
        if not username:
            return Response({"detail": "username is required."}, status=status.HTTP_400_BAD_REQUEST)

        user = get_object_or_404(User, username=username)
        account = _ensure_user_account(user)
        if account.status in {UserAccount.STATUS_DELETED, UserAccount.STATUS_SUSPENDED}:
            return Response({"detail": "Account is disabled."}, status=status.HTTP_403_FORBIDDEN)
        login(request, user)
        start_user_session(request=request, user=user, auth_method=UserSession.AUTH_SESSION)
        log_security_event(
            "auth.magic_login",
            request=request,
            actor=user,
            target_type="user",
            target_id=str(user.pk),
            metadata={"enabled": bool(getattr(settings, "AUTH_MAGIC_LOGIN_ENABLED", settings.DEBUG))},
        )

        next_url = request.query_params.get("next") or ""
        if next_url:
            if next_url.startswith("//"):
                return Response({"detail": "Unsafe redirect target."}, status=status.HTTP_400_BAD_REQUEST)
            if url_has_allowed_host_and_scheme(
                next_url,
                allowed_hosts=set(settings.ALLOWED_HOSTS),
                require_https=not settings.DEBUG,
            ):
                return HttpResponseRedirect(next_url)
            return Response({"detail": "Unsafe redirect target."}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {
                "authenticated": True,
                "has_users": True,
                "user": _auth_user_payload(user, request=request),
            }
        )


class AuthTokenIssueView(APIView):
    """Issue short-lived access token + rotating refresh token."""

    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = []

    def get_throttles(self):
        from .throttles import AuthSessionThrottle

        return [AuthSessionThrottle()]

    def post(self, request):
        account = _ensure_user_account(request.user)
        if account.status in {UserAccount.STATUS_DELETED, UserAccount.STATUS_SUSPENDED, UserAccount.STATUS_LOCKED}:
            return Response({"detail": "Account is not allowed to mint tokens."}, status=status.HTTP_403_FORBIDDEN)
        active_session_id = request.session.get("active_user_session_id")
        session_record = None
        if active_session_id:
            session_record = UserSession.objects.filter(
                pk=active_session_id,
                user=request.user,
                revoked_at__isnull=True,
            ).first()
        if session_record is None:
            session_record = start_user_session(request=request, user=request.user, auth_method=UserSession.AUTH_SESSION)

        refresh_token, refresh_record = issue_security_token(
            user=request.user,
            purpose=SecurityToken.PURPOSE_REFRESH,
            ttl_seconds=getattr(settings, "AUTH_REFRESH_TOKEN_TTL_SECONDS", 60 * 60 * 24 * 30),
            metadata={"issued_from": "session", "session_id": session_record.id},
            session=session_record,
            request=request,
        )
        session_record.refresh_token_hash = refresh_record.token_hash
        session_record.save(update_fields=["refresh_token_hash", "updated_at"])
        access_token, ttl = _build_access_token_for_user(request.user)
        log_security_event(
            "auth.token.issue",
            request=request,
            actor=request.user,
            target_type="user",
            target_id=str(request.user.pk),
        )
        return Response(
            {
                "access_token": access_token,
                "access_token_expires_in": ttl,
                "refresh_token": refresh_token,
                "session_id": session_record.id,
            }
        )


class AuthTokenRefreshView(APIView):
    """Rotate refresh token and return a new short-lived access token."""

    permission_classes = [permissions.AllowAny]
    throttle_classes = []

    def get_throttles(self):
        from .throttles import AuthSessionThrottle

        return [AuthSessionThrottle()]

    def post(self, request):
        serializer = AuthTokenRefreshSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        rotated = rotate_refresh_token(
            raw_token=serializer.validated_data["refresh_token"],
            ttl_seconds=getattr(settings, "AUTH_REFRESH_TOKEN_TTL_SECONDS", 60 * 60 * 24 * 30),
            request=request,
        )
        if rotated is None:
            return Response({"detail": "Invalid refresh token."}, status=status.HTTP_401_UNAUTHORIZED)

        user, new_refresh = rotated
        account = _ensure_user_account(user)
        if not user.is_active or account.status in {UserAccount.STATUS_DELETED, UserAccount.STATUS_SUSPENDED}:
            return Response({"detail": "User is inactive."}, status=status.HTTP_401_UNAUTHORIZED)
        access_token, ttl = _build_access_token_for_user(user)
        log_security_event(
            "auth.token.refresh",
            request=request,
            actor=user,
            target_type="user",
            target_id=str(user.pk),
        )
        return Response(
            {
                "access_token": access_token,
                "access_token_expires_in": ttl,
                "refresh_token": new_refresh,
            }
        )


class AuthTokenRevokeView(APIView):
    """Revoke a refresh token."""

    permission_classes = [permissions.AllowAny]
    throttle_classes = []

    def get_throttles(self):
        from .throttles import AuthSessionThrottle

        return [AuthSessionThrottle()]

    def post(self, request):
        serializer = AuthTokenRevokeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        revoked = revoke_refresh_token(serializer.validated_data["refresh_token"])
        log_security_event(
            "auth.token.revoke",
            request=request,
            actor=request.user if request.user.is_authenticated else None,
            success=revoked,
        )
        return Response({"revoked": bool(revoked)})


class AuthAPIKeyListCreateView(APIView):
    """List and create personal API keys."""

    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = []

    def get_throttles(self):
        from .throttles import AuthSessionThrottle

        return [AuthSessionThrottle()]

    def get(self, request):
        keys = (
            PersonalAPIKey.objects.filter(user=request.user)
            .order_by("-created_at")
            .values(
                "id",
                "name",
                "key_prefix",
                "scopes",
                "created_at",
                "expires_at",
                "last_used_at",
                "last_used_ip",
                "revoked_at",
            )
        )
        return Response(
            {
                "results": [
                    {
                        "id": item["id"],
                        "name": item["name"],
                        "token_hint": f"{item['key_prefix']}***",
                        "scopes": item.get("scopes") or [],
                        "created_at": item["created_at"],
                        "expires_at": item["expires_at"],
                        "last_used_at": item["last_used_at"],
                        "last_used_ip": item["last_used_ip"],
                        "revoked_at": item["revoked_at"],
                    }
                    for item in keys
                ]
            }
        )

    def post(self, request):
        serializer = APIKeyCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        name = serializer.validated_data["name"].strip() or "default"
        raw_key = f"wbk_{secrets.token_urlsafe(32)}"
        key_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
        expires_in_days = serializer.validated_data.get("expires_in_days")
        expires_at = timezone.now() + timedelta(days=int(expires_in_days)) if expires_in_days else None
        scopes = serializer.validated_data.get("scopes") or ["sites:read"]
        record = PersonalAPIKey.objects.create(
            user=request.user,
            name=name,
            key_prefix=raw_key[:12],
            key_hash=key_hash,
            scopes=scopes,
            expires_at=expires_at,
        )
        log_security_event(
            "auth.api_key.create",
            request=request,
            actor=request.user,
            target_type="api_key",
            target_id=str(record.id),
        )
        return Response(
            {
                "id": record.id,
                "name": record.name,
                "token": raw_key,
                "scopes": record.scopes,
                "expires_at": record.expires_at,
            },
            status=status.HTTP_201_CREATED,
        )


class AuthAPIKeyRevokeView(APIView):
    """Revoke a personal API key."""

    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = []

    def get_throttles(self):
        from .throttles import AuthSessionThrottle

        return [AuthSessionThrottle()]

    def post(self, request, key_id: int):
        serializer = APIKeyRevokeSerializer(data={"key_id": key_id})
        serializer.is_valid(raise_exception=True)
        key = get_object_or_404(PersonalAPIKey, pk=key_id, user=request.user)
        key.revoked_at = timezone.now()
        key.save(update_fields=["revoked_at", "updated_at"])
        log_security_event(
            "auth.api_key.revoke",
            request=request,
            actor=request.user,
            target_type="api_key",
            target_id=str(key.id),
        )
        return Response({"revoked": True})


class AuthEmailVerificationRequestView(APIView):
    """Generate and dispatch single-use email verification token."""

    permission_classes = [permissions.AllowAny]
    throttle_classes = []

    def get_throttles(self):
        from .throttles import EmailVerificationThrottle

        return [EmailVerificationThrottle()]

    def post(self, request):
        serializer = EmailVerificationRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = (serializer.validated_data.get("email") or "").strip()
        if request.user.is_authenticated:
            target_user = request.user
        elif email:
            target_user = User.objects.filter(email__iexact=email).first()
        else:
            target_user = None

        if target_user is not None and target_user.email:
            raw_token, _ = issue_security_token(
                user=target_user,
                purpose=SecurityToken.PURPOSE_EMAIL_VERIFY,
                ttl_seconds=getattr(settings, "AUTH_EMAIL_VERIFICATION_TOKEN_TTL_SECONDS", 60 * 60 * 24),
                metadata={"email": target_user.email},
            )
            base_url = (getattr(settings, "APP_URL", "") or "").rstrip("/")
            link = f"{base_url}/verify-email?token={raw_token}" if base_url else raw_token
            send_mail(
                subject="Verify your account email",
                message=f"Use this verification token: {raw_token}\n\nVerification URL: {link}",
                from_email=getattr(settings, "DEFAULT_FROM_EMAIL", ""),
                recipient_list=[target_user.email],
                fail_silently=True,
            )
            log_security_event(
                "auth.email_verification.request",
                request=request,
                actor=target_user if request.user.is_authenticated else None,
                target_type="user",
                target_id=str(target_user.pk),
            )
        return Response({"detail": "If the account exists, a verification email has been sent."}, status=202)


class AuthEmailVerificationConfirmView(APIView):
    """Consume single-use email verification token."""

    permission_classes = [permissions.AllowAny]
    throttle_classes = []

    def get_throttles(self):
        from .throttles import EmailVerificationThrottle

        return [EmailVerificationThrottle()]

    def post(self, request):
        serializer = EmailVerificationConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        token_record = consume_security_token(
            raw_token=serializer.validated_data["token"],
            purpose=SecurityToken.PURPOSE_EMAIL_VERIFY,
        )
        if token_record is None:
            return Response({"detail": "Invalid or expired verification token."}, status=status.HTTP_400_BAD_REQUEST)

        state, _ = UserSecurityState.objects.get_or_create(user=token_record.user)
        state.email_verified_at = timezone.now()
        state.save(update_fields=["email_verified_at", "updated_at"])
        account = _ensure_user_account(token_record.user)
        account.email_verified_at = state.email_verified_at
        account.save(update_fields=["email_verified_at", "updated_at"])
        log_security_event(
            "auth.email_verification.confirm",
            request=request,
            actor=token_record.user,
            target_type="user",
            target_id=str(token_record.user.pk),
        )
        return Response({"verified": True})


class AuthPasswordResetRequestView(APIView):
    """Generate and dispatch single-use password reset token."""

    permission_classes = [permissions.AllowAny]
    throttle_classes = []

    def get_throttles(self):
        from .throttles import PasswordResetThrottle

        return [PasswordResetThrottle()]

    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"]
        target_user = User.objects.filter(email__iexact=email).first()

        if target_user is not None and target_user.email:
            raw_token, _ = issue_security_token(
                user=target_user,
                purpose=SecurityToken.PURPOSE_PASSWORD_RESET,
                ttl_seconds=getattr(settings, "AUTH_PASSWORD_RESET_TOKEN_TTL_SECONDS", 60 * 30),
                metadata={"email": target_user.email},
            )
            base_url = (getattr(settings, "APP_URL", "") or "").rstrip("/")
            link = f"{base_url}/reset-password?token={raw_token}" if base_url else raw_token
            send_mail(
                subject="Password reset request",
                message=f"Use this reset token: {raw_token}\n\nReset URL: {link}",
                from_email=getattr(settings, "DEFAULT_FROM_EMAIL", ""),
                recipient_list=[target_user.email],
                fail_silently=True,
            )
            log_security_event(
                "auth.password_reset.request",
                request=request,
                target_type="user",
                target_id=str(target_user.pk),
            )
        # Avoid account enumeration
        return Response({"detail": "If the account exists, a reset email has been sent."}, status=202)


class AuthPasswordResetConfirmView(APIView):
    """Consume reset token and rotate account secrets."""

    permission_classes = [permissions.AllowAny]
    throttle_classes = []

    def get_throttles(self):
        from .throttles import PasswordResetThrottle

        return [PasswordResetThrottle()]

    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        token_record = consume_security_token(
            raw_token=serializer.validated_data["token"],
            purpose=SecurityToken.PURPOSE_PASSWORD_RESET,
        )
        if token_record is None:
            return Response({"detail": "Invalid or expired reset token."}, status=status.HTTP_400_BAD_REQUEST)

        user = token_record.user
        user.set_password(serializer.validated_data["password"])
        user.save(update_fields=["password"])

        # Revoke outstanding refresh tokens on password reset.
        revoke_all_refresh_tokens(user)

        state, _ = UserSecurityState.objects.get_or_create(user=user)
        state.last_password_change_at = timezone.now()
        state.failed_login_count = 0
        state.locked_until = None
        state.access_token_version = int(state.access_token_version or 1) + 1
        state.save(
            update_fields=[
                "last_password_change_at",
                "failed_login_count",
                "locked_until",
                "access_token_version",
                "updated_at",
            ]
        )
        UserSession.objects.filter(user=user, revoked_at__isnull=True).update(revoked_at=timezone.now(), updated_at=timezone.now())
        account = _ensure_user_account(user)
        if account.status == UserAccount.STATUS_LOCKED:
            account.status = UserAccount.STATUS_ACTIVE
            account.save(update_fields=["status", "updated_at"])

        log_security_event(
            "auth.password_reset.confirm",
            request=request,
            actor=user,
            target_type="user",
            target_id=str(user.pk),
        )
        return Response({"reset": True})


class AuthChangePasswordView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = []

    def get_throttles(self):
        from .throttles import AuthSessionThrottle

        return [AuthSessionThrottle()]

    def post(self, request):
        serializer = AuthChangePasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = request.user
        if not user.check_password(serializer.validated_data["current_password"]):
            return Response({"detail": "Current password is invalid."}, status=status.HTTP_400_BAD_REQUEST)

        user.set_password(serializer.validated_data["new_password"])
        user.save(update_fields=["password"])

        state, _ = UserSecurityState.objects.get_or_create(user=user)
        state.last_password_change_at = timezone.now()
        state.access_token_version = int(state.access_token_version or 1) + 1
        state.failed_login_count = 0
        state.locked_until = None
        state.save(
            update_fields=[
                "last_password_change_at",
                "access_token_version",
                "failed_login_count",
                "locked_until",
                "updated_at",
            ]
        )

        revoke_all_refresh_tokens(user)
        current_session_id = request.session.get("active_user_session_id")
        revoke_other_sessions(user=user, keep_session_id=current_session_id)
        log_security_event(
            "auth.password.change",
            request=request,
            actor=user,
            target_type="user",
            target_id=str(user.pk),
        )
        return Response({"changed": True})


def _consume_recovery_code(*, user, code: str) -> bool:
    code_hash = hash_recovery_code(code)
    recovery = (
        MFARecoveryCode.objects.filter(
            user=user,
            code_hash=code_hash,
            used_at__isnull=True,
        )
        .order_by("-created_at")
        .first()
    )
    if recovery is None:
        return False
    if not verify_recovery_code(code, recovery.code_hash):
        return False
    recovery.used_at = timezone.now()
    recovery.save(update_fields=["used_at", "updated_at"])
    return True


class AuthMFAChallengeVerifyView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = []

    def get_throttles(self):
        from .throttles import AuthSessionThrottle

        return [AuthSessionThrottle()]

    def post(self, request):
        serializer = AuthMFAChallengeVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        token_record = consume_security_token(
            raw_token=serializer.validated_data["challenge_token"],
            purpose=SecurityToken.PURPOSE_MFA_CHALLENGE,
        )
        if token_record is None:
            return Response({"detail": "Invalid or expired MFA challenge token."}, status=status.HTTP_400_BAD_REQUEST)

        user = token_record.user
        account = _ensure_user_account(user)
        if not account.mfa_enabled:
            return Response({"detail": "MFA is not enabled for this user."}, status=status.HTTP_400_BAD_REQUEST)

        code = serializer.validated_data.get("totp_code") or ""
        recovery_code = serializer.validated_data.get("recovery_code") or ""
        device = getattr(user, "mfa_totp_device", None)
        verified = False
        method = ""
        if code and device and device.is_confirmed and verify_totp(device.secret, code):
            verified = True
            method = "totp"
            device.last_used_at = timezone.now()
            device.save(update_fields=["last_used_at", "updated_at"])
        elif recovery_code and _consume_recovery_code(user=user, code=recovery_code):
            verified = True
            method = "recovery_code"

        if not verified:
            log_security_event(
                "auth.login.mfa_failed",
                request=request,
                actor=user,
                target_type="user",
                target_id=str(user.pk),
                success=False,
            )
            return Response({"detail": "Invalid MFA code."}, status=status.HTTP_400_BAD_REQUEST)

        login(request, user)
        request.session.set_expiry(getattr(settings, "SESSION_COOKIE_AGE", 1209600))
        start_user_session(request=request, user=user, auth_method=UserSession.AUTH_SESSION)
        state, _ = UserSecurityState.objects.get_or_create(user=user)
        state.last_mfa_at = timezone.now()
        state.save(update_fields=["last_mfa_at", "updated_at"])

        log_security_event(
            "auth.login.success",
            request=request,
            actor=user,
            target_type="user",
            target_id=str(user.pk),
            metadata={"mfa_method": method},
        )
        return Response(
            {
                "authenticated": True,
                "has_users": True,
                "user": _auth_user_payload(user, request=request),
            }
        )


class AuthMFATOTPSetupView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = []

    def get_throttles(self):
        from .throttles import AuthSessionThrottle

        return [AuthSessionThrottle()]

    def post(self, request):
        serializer = AuthMFATOTPSetupSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if serializer.validated_data.get("password") and not request.user.check_password(serializer.validated_data["password"]):
            return Response({"detail": "Invalid password."}, status=status.HTTP_400_BAD_REQUEST)

        secret = generate_totp_secret()
        device, _ = MFATOTPDevice.objects.get_or_create(user=request.user, defaults={"secret": secret})
        if serializer.validated_data.get("regenerate") or device.is_confirmed is False:
            device.secret = secret
            device.is_confirmed = False
            device.confirmed_at = None
            device.save(update_fields=["secret", "is_confirmed", "confirmed_at", "updated_at"])
        account = _ensure_user_account(request.user)
        otp_uri = build_totp_uri(
            secret=device.secret,
            account_name=account.email or request.user.username,
            issuer=getattr(settings, "APP_NAME", "Website Builder"),
        )
        return Response(
            {
                "secret": device.secret,
                "otpauth_url": otp_uri,
                "mfa_enabled": bool(account.mfa_enabled),
            }
        )


class AuthMFATOTPVerifyView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = []

    def get_throttles(self):
        from .throttles import AuthSessionThrottle

        return [AuthSessionThrottle()]

    def post(self, request):
        serializer = AuthMFATOTPVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        device = get_object_or_404(MFATOTPDevice, user=request.user)
        if not verify_totp(device.secret, serializer.validated_data["code"]):
            return Response({"detail": "Invalid TOTP code."}, status=status.HTTP_400_BAD_REQUEST)

        device.is_confirmed = True
        device.confirmed_at = timezone.now()
        device.last_used_at = timezone.now()
        device.save(update_fields=["is_confirmed", "confirmed_at", "last_used_at", "updated_at"])

        account = _ensure_user_account(request.user)
        account.mfa_enabled = True
        account.save(update_fields=["mfa_enabled", "updated_at"])
        state, _ = UserSecurityState.objects.get_or_create(user=request.user)
        state.last_mfa_at = timezone.now()
        state.save(update_fields=["last_mfa_at", "updated_at"])

        MFARecoveryCode.objects.filter(user=request.user, used_at__isnull=True).delete()
        plain_codes = generate_recovery_codes()
        MFARecoveryCode.objects.bulk_create(
            [
                MFARecoveryCode(
                    user=request.user,
                    code_hash=hash_recovery_code(code),
                )
                for code in plain_codes
            ]
        )
        log_security_event(
            "auth.mfa.enable",
            request=request,
            actor=request.user,
            target_type="user",
            target_id=str(request.user.pk),
        )
        return Response({"mfa_enabled": True, "recovery_codes": plain_codes})


class AuthMFARecoveryCodesRegenerateView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = []

    def get_throttles(self):
        from .throttles import AuthSessionThrottle

        return [AuthSessionThrottle()]

    def post(self, request):
        serializer = AuthMFABackupCodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        device = getattr(request.user, "mfa_totp_device", None)
        if device is None or not device.is_confirmed:
            return Response({"detail": "MFA is not configured."}, status=status.HTTP_400_BAD_REQUEST)

        totp_code = serializer.validated_data.get("totp_code") or ""
        recovery_code = serializer.validated_data.get("recovery_code") or ""
        if totp_code:
            verified = verify_totp(device.secret, totp_code)
        elif recovery_code:
            verified = _consume_recovery_code(user=request.user, code=recovery_code)
        else:
            verified = False
        if not verified:
            return Response({"detail": "Invalid verification code."}, status=status.HTTP_400_BAD_REQUEST)

        MFARecoveryCode.objects.filter(user=request.user, used_at__isnull=True).delete()
        plain_codes = generate_recovery_codes()
        MFARecoveryCode.objects.bulk_create(
            [MFARecoveryCode(user=request.user, code_hash=hash_recovery_code(code)) for code in plain_codes]
        )
        log_security_event(
            "auth.mfa.recovery_codes.regenerate",
            request=request,
            actor=request.user,
            target_type="user",
            target_id=str(request.user.pk),
        )
        return Response({"recovery_codes": plain_codes})


class AuthSessionListView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = []

    def get_throttles(self):
        from .throttles import AuthSessionThrottle

        return [AuthSessionThrottle()]

    def get(self, request):
        current_session_id = request.session.get("active_user_session_id")
        sessions = active_sessions_for_user(request.user)
        return Response(
            {
                "results": [
                    {
                        "id": session.id,
                        "auth_method": session.auth_method,
                        "device_id": session.device_id,
                        "device_name": session.device_name,
                        "ip_address": session.ip_address,
                        "user_agent": session.user_agent,
                        "last_seen_at": session.last_seen_at,
                        "created_at": session.created_at,
                        "current": bool(current_session_id and int(current_session_id) == session.id),
                    }
                    for session in sessions
                ]
            }
        )


class AuthSessionRevokeView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = []

    def get_throttles(self):
        from .throttles import AuthSessionThrottle

        return [AuthSessionThrottle()]

    def post(self, request):
        serializer = AuthSessionRevokeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        session_id = serializer.validated_data.get("session_id")
        device_id = (serializer.validated_data.get("device_id") or "").strip()
        revoked = False
        target_id = ""
        if session_id:
            target_id = str(session_id)
            revoked = revoke_session(user=request.user, session_id=session_id)
        elif device_id:
            target_id = device_id
            revoked = bool(
                UserSession.objects.filter(
                    user=request.user,
                    device_id=device_id,
                    revoked_at__isnull=True,
                ).update(revoked_at=timezone.now(), updated_at=timezone.now())
            )
        log_security_event(
            "auth.session.revoke",
            request=request,
            actor=request.user,
            target_type="user_session",
            target_id=target_id,
            success=revoked,
        )
        return Response({"revoked": bool(revoked)})


class AuthSessionRevokeOthersView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = []

    def get_throttles(self):
        from .throttles import AuthSessionThrottle

        return [AuthSessionThrottle()]

    def post(self, request):
        current_session_id = request.session.get("active_user_session_id")
        revoked_count = revoke_other_sessions(user=request.user, keep_session_id=current_session_id)
        revoke_all_refresh_tokens(request.user)
        log_security_event(
            "auth.session.revoke_others",
            request=request,
            actor=request.user,
            target_type="user",
            target_id=str(request.user.pk),
            metadata={"revoked_count": revoked_count},
        )
        return Response({"revoked_count": int(revoked_count)})


class AuthSocialLoginView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = []

    def get_throttles(self):
        from .throttles import AuthSessionThrottle

        return [AuthSessionThrottle()]

    def post(self, request):
        serializer = AuthSocialLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        provider = serializer.validated_data["provider"]
        adapter = social_provider_registry.get(provider)
        if adapter is None:
            return Response({"detail": f"Social provider '{provider}' is not configured."}, status=status.HTTP_501_NOT_IMPLEMENTED)
        identity = adapter.verify(access_token=serializer.validated_data["access_token"])
        email = (identity.email or "").strip().lower()
        if not email:
            return Response({"detail": "Social identity did not provide an email."}, status=status.HTTP_400_BAD_REQUEST)
        user = User.objects.filter(email__iexact=email).first()
        if user is None:
            base = (email.split("@")[0] or provider).strip()
            username = base
            suffix = 2
            while User.objects.filter(username=username).exists():
                username = f"{base}{suffix}"
                suffix += 1
            user = User.objects.create_user(username=username, email=email, password=secrets.token_urlsafe(32))
        account = _ensure_user_account(user)
        if identity.display_name and not account.display_name:
            account.display_name = identity.display_name[:160]
        if identity.avatar_url and not account.avatar_url:
            account.avatar_url = identity.avatar_url[:600]
        if identity.email_verified and not account.email_verified_at:
            account.email_verified_at = timezone.now()
        account.save()

        login(request, user)
        start_user_session(request=request, user=user, auth_method=UserSession.AUTH_SESSION)
        log_security_event(
            "auth.social_login",
            request=request,
            actor=user,
            target_type="user",
            target_id=str(user.pk),
            metadata={"provider": provider},
        )
        return Response({"authenticated": True, "has_users": True, "user": _auth_user_payload(user, request=request)})


class AuthActivityTimelineView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = []

    def get_throttles(self):
        from .throttles import AuthSessionThrottle

        return [AuthSessionThrottle()]

    def get(self, request):
        limit = min(max(int(request.query_params.get("limit", 100)), 1), 500)
        events = (
            SecurityAuditLog.objects.filter(
                models.Q(actor=request.user)
                | models.Q(target_type="user", target_id=str(request.user.pk))
            )
            .order_by("-created_at")[:limit]
        )
        return Response({"results": UserActivitySerializer(events, many=True).data})


class SiteViewSet(SitePermissionMixin, viewsets.ModelViewSet):
    serializer_class = SiteSerializer
    site_write_permission = SitePermission.MANAGE

    def get_queryset(self):
        from .workspace_views import filter_sites_by_permission
        ensure_seed_data()
        queryset = Site.objects.prefetch_related(
            "locales",
            "pages__revisions",
            "pages__translations__locale",
        ).order_by("name")
        return filter_sites_by_permission(self.request.user, queryset)

    def perform_create(self, serializer):
        from .workspace_views import resolve_workspace_for_site_creation

        workspace = resolve_workspace_for_site_creation(
            self.request.user,
            self.request.data.get("workspace"),
        )
        serializer.save(workspace=workspace)

    @action(detail=True, methods=["post"])
    def import_mirror(self, request, pk=None):
        site = self.get_object()
        serializer = SiteMirrorImportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            result = import_mirrored_site(
                site,
                source_path=serializer.validated_data["source_path"],
                publish=serializer.validated_data["publish"],
                replace_existing=serializer.validated_data["replace_existing"],
            )
        except ValueError as exc:
            raise ValidationError({"source_path": str(exc)}) from exc
        site.refresh_from_db()
        payload = SiteSerializer(site, context={"request": request}).data
        return Response({"site": payload, **result})

    @action(detail=True, methods=["get"], url_path="members")
    def members(self, request, pk=None):
        site = self.get_object()
        if not self.check_site_manage_permission(site):
            raise PermissionDenied("You don't have permission to manage this site.")
        memberships = site.memberships.select_related("user", "granted_by").order_by("role", "user__username")
        return Response(SiteMembershipSerializer(memberships, many=True, context={"request": request}).data)

    @members.mapping.post
    def upsert_member(self, request, pk=None):
        site = self.get_object()
        if not self.check_site_manage_permission(site):
            raise PermissionDenied("You don't have permission to manage this site.")
        serializer = SiteMembershipUpsertSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = get_object_or_404(User, pk=serializer.validated_data["user_id"])
        membership, created = SiteMembership.objects.get_or_create(
            site=site,
            user=user,
            defaults={
                "role": serializer.validated_data["role"],
                "status": serializer.validated_data.get("status", SiteMembership.STATUS_ACTIVE),
                "granted_by": request.user,
                "accepted_at": timezone.now(),
            },
        )
        if not created:
            membership.role = serializer.validated_data["role"]
            if serializer.validated_data.get("status"):
                membership.status = serializer.validated_data["status"]
            membership.granted_by = request.user
            if membership.accepted_at is None:
                membership.accepted_at = timezone.now()
            membership.save(update_fields=["role", "status", "granted_by", "accepted_at", "updated_at"])
        log_security_event(
            "site.membership.upsert",
            request=request,
            actor=request.user,
            target_type="site_membership",
            target_id=str(membership.pk),
            metadata={"site_id": site.pk, "created": created},
        )
        return Response(
            SiteMembershipSerializer(membership, context={"request": request}).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    @action(detail=True, methods=["delete"], url_path=r"members/(?P<membership_id>[^/.]+)")
    def remove_member(self, request, pk=None, membership_id=None):
        site = self.get_object()
        if not self.check_site_manage_permission(site):
            raise PermissionDenied("You don't have permission to manage this site.")
        membership = get_object_or_404(SiteMembership, pk=membership_id, site=site)
        membership.delete()
        log_security_event(
            "site.membership.delete",
            request=request,
            actor=request.user,
            target_type="site_membership",
            target_id=str(membership_id),
            metadata={"site_id": site.pk},
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class SiteLocaleViewSet(SitePermissionMixin, viewsets.ModelViewSet):
    serializer_class = SiteLocaleSerializer

    def get_queryset(self):
        queryset = SiteLocale.objects.select_related("site").order_by("site__name", "-is_default", "code")
        site_id = self.request.query_params.get("site")
        if site_id:
            queryset = queryset.filter(site_id=site_id)
        return self.filter_by_site_permission(queryset)

    def perform_create(self, serializer):
        locale = super().perform_create(serializer)
        sync_site_localization_settings(locale.site)

    def perform_update(self, serializer):
        locale = super().perform_update(serializer)
        sync_site_localization_settings(locale.site)

    def perform_destroy(self, instance):
        site = instance.site
        was_default = instance.is_default
        super().perform_destroy(instance)
        replacement = site.locales.filter(is_enabled=True).order_by("code").first() or site.locales.order_by("code").first()
        if was_default and replacement and not replacement.is_default:
            replacement.is_default = True
            replacement.save(update_fields=["is_default", "updated_at"])
        sync_site_localization_settings(site)


class PageViewSet(SitePermissionMixin, viewsets.ModelViewSet):
    serializer_class = PageSerializer

    def get_queryset(self):
        from .workspace_views import filter_sites_by_permission
        ensure_seed_data()
        queryset = (
            Page.objects.select_related("site")
            .prefetch_related("revisions", "translations__locale")
            .order_by("site__name", "-is_homepage", "title")
        )
        site_id = self.request.query_params.get("site")
        if site_id:
            queryset = queryset.filter(site_id=site_id)
        return self.filter_by_site_permission(queryset)

    def perform_create(self, serializer):
        page = super().perform_create(serializer)
        queue_search_index("page", page.id)

    def perform_update(self, serializer):
        page = super().perform_update(serializer)
        queue_search_index("page", page.id)
        trigger_webhooks(page.site, "page.updated", {"page_id": page.id, "title": page.title, "path": page.path})

    @action(detail=True, methods=["post"])
    def save_builder(self, request, pk=None):
        page = self.get_object()
        serializer = BuilderSaveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            build_page_payload(page, serializer.validated_data)
        except DjangoValidationError as exc:
            return Response(exc.message_dict if hasattr(exc, "message_dict") else {"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)
        sync_homepage_state(page)
        try:
            ensure_unique_page_path(page)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        page.status = Page.STATUS_DRAFT
        page.save()
        create_revision(page, "Draft snapshot")
        queue_search_index("page", page.id)
        return Response(PageSerializer(page, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def publish(self, request, pk=None):
        page = self.get_object()
        serializer = BuilderSaveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            build_page_payload(page, serializer.validated_data)
        except DjangoValidationError as exc:
            return Response(exc.message_dict if hasattr(exc, "message_dict") else {"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)
        sync_homepage_state(page)
        try:
            ensure_unique_page_path(page)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        page.status = Page.STATUS_PUBLISHED
        page.published_at = timezone.now()
        page.save()
        create_revision(page, "Published snapshot")
        create_publish_snapshot(
            site=page.site,
            target_type=PublishSnapshot.TARGET_PAGE,
            target_id=page.id,
            instance=page,
            actor=request.user,
            revision_label="Published snapshot",
            metadata={"source": "builder.page.publish"},
        )
        queue_search_index("page", page.id)
        trigger_webhooks(page.site, "page.published", {"page_id": page.id, "title": page.title, "path": page.path})
        return Response(PageSerializer(page, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def schedule(self, request, pk=None):
        """Schedule a page for future publishing."""
        page = self.get_object()
        scheduled_at = request.data.get("scheduled_at")
        if not scheduled_at:
            return Response({"detail": "scheduled_at is required"}, status=status.HTTP_400_BAD_REQUEST)

        from dateutil.parser import parse as parse_date
        try:
            scheduled_time = parse_date(scheduled_at)
        except (ValueError, TypeError):
            return Response({"detail": "Invalid date format"}, status=status.HTTP_400_BAD_REQUEST)

        page.scheduled_at = scheduled_time
        page.save(update_fields=["scheduled_at", "updated_at"])

        # Create job for scheduled publishing
        from .jobs import schedule_content_publish
        schedule_content_publish("page", page.id, scheduled_time)

        return Response(PageSerializer(page, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def validate_layout(self, request, pk=None):
        page = self.get_object()
        payload = request.data if isinstance(request.data, dict) else {}
        try:
            normalized = normalize_page_content(
                title=payload.get("title") or page.title,
                slug=payload.get("slug") or page.slug,
                path=payload.get("path") or page.path,
                is_homepage=bool(payload.get("is_homepage", page.is_homepage)),
                status=payload.get("status") or page.status,
                locale_code="",
                builder_data=payload.get("builder_data", page.builder_data),
                seo=payload.get("seo", page.seo),
                page_settings=payload.get("page_settings", page.page_settings),
                html=payload.get("html", page.html),
                css=payload.get("css", page.css),
                js=payload.get("js", page.js),
                schema_version=payload.get("builder_schema_version", page.builder_schema_version),
                strict=True,
            )
        except DjangoValidationError as exc:
            detail = exc.message_dict if hasattr(exc, "message_dict") else {"detail": exc.messages}
            return Response({"valid": False, "errors": detail}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            {
                "valid": True,
                "builder_schema_version": normalized["schema_version"],
                "warnings": [],
            }
        )


class PageTranslationViewSet(SitePermissionMixin, viewsets.ModelViewSet):
    serializer_class = PageTranslationSerializer
    site_lookup_field = "page__site"

    def get_queryset(self):
        queryset = (
            PageTranslation.objects.select_related("page", "page__site", "locale")
            .order_by("page__site__name", "page__title", "locale__code")
        )
        page_id = self.request.query_params.get("page_id") or self.request.query_params.get("page")
        locale_id = self.request.query_params.get("locale")
        if page_id:
            queryset = queryset.filter(page_id=page_id)
        if locale_id:
            queryset = queryset.filter(locale_id=locale_id)
        return self.filter_by_site_permission(queryset)

    def perform_create(self, serializer):
        translation = super().perform_create(serializer)
        queue_search_index("page", translation.page_id)

    def perform_update(self, serializer):
        translation = super().perform_update(serializer)
        queue_search_index("page", translation.page_id)

    def perform_destroy(self, instance):
        page = instance.page
        super().perform_destroy(instance)
        queue_search_index("page", page.id)

    @action(detail=True, methods=["post"])
    def save_builder(self, request, pk=None):
        translation = self.get_object()
        serializer = BuilderSaveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            build_translation_payload(translation, serializer.validated_data)
        except DjangoValidationError as exc:
            return Response(exc.message_dict if hasattr(exc, "message_dict") else {"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)
        try:
            PageTranslationSerializer(instance=translation, data={"page": translation.page_id, "locale": translation.locale_id, "slug": translation.slug, "title": translation.title}, partial=True).is_valid(raise_exception=True)
        except serializers.ValidationError as exc:
            return Response(exc.detail, status=status.HTTP_400_BAD_REQUEST)

        translation.status = PageTranslation.STATUS_DRAFT
        translation.save()
        queue_search_index("page", translation.page_id)
        return Response(PageTranslationSerializer(translation, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def publish(self, request, pk=None):
        translation = self.get_object()
        serializer = BuilderSaveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            build_translation_payload(translation, serializer.validated_data)
        except DjangoValidationError as exc:
            return Response(exc.message_dict if hasattr(exc, "message_dict") else {"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)
        try:
            PageTranslationSerializer(instance=translation, data={"page": translation.page_id, "locale": translation.locale_id, "slug": translation.slug, "title": translation.title}, partial=True).is_valid(raise_exception=True)
        except serializers.ValidationError as exc:
            return Response(exc.detail, status=status.HTTP_400_BAD_REQUEST)

        translation.status = PageTranslation.STATUS_PUBLISHED
        translation.published_at = timezone.now()
        translation.save()
        queue_search_index("page", translation.page_id)
        trigger_webhooks(
            translation.page.site,
            "page.translation_published",
            {
                "page_id": translation.page_id,
                "translation_id": translation.id,
                "locale": translation.locale.code,
                "title": translation.title,
                "path": translation.path,
            },
        )
        return Response(PageTranslationSerializer(translation, context={"request": request}).data)


class PageExperimentViewSet(SitePermissionMixin, viewsets.ModelViewSet):
    serializer_class = PageExperimentSerializer
    pagination_class = None

    def get_queryset(self):
        queryset = (
            PageExperiment.objects.select_related("site", "page", "locale")
            .prefetch_related("variants", "events")
            .order_by("page__site__name", "page__title", "-updated_at")
        )
        site_id = self.request.query_params.get("site")
        page_id = self.request.query_params.get("page_id") or self.request.query_params.get("page")
        locale_id = self.request.query_params.get("locale")
        status_filter = self.request.query_params.get("status")
        if site_id:
            queryset = queryset.filter(site_id=site_id)
        if page_id:
            queryset = queryset.filter(page_id=page_id)
        if locale_id == "null":
            queryset = queryset.filter(locale__isnull=True)
        elif locale_id:
            queryset = queryset.filter(locale_id=locale_id)
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        return self.filter_by_site_permission(queryset)

    def perform_create(self, serializer):
        super().perform_create(serializer)

    def perform_update(self, serializer):
        super().perform_update(serializer)

    @action(detail=True, methods=["post"])
    def activate(self, request, pk=None):
        experiment = self.get_object()
        serializer = self.get_serializer(experiment, data={"status": PageExperiment.STATUS_ACTIVE}, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save(status=PageExperiment.STATUS_ACTIVE)
        return Response(self.get_serializer(experiment).data)

    @action(detail=True, methods=["post"])
    def pause(self, request, pk=None):
        experiment = self.get_object()
        experiment.status = PageExperiment.STATUS_PAUSED
        experiment.save(update_fields=["status", "updated_at"])
        return Response(self.get_serializer(experiment).data)

    @action(detail=True, methods=["post"])
    def archive(self, request, pk=None):
        experiment = self.get_object()
        experiment.status = PageExperiment.STATUS_ARCHIVED
        experiment.save(update_fields=["status", "updated_at"])
        return Response(self.get_serializer(experiment).data)


def _review_collaborators_for_site(site: Site, request_user=None):
    workspace = site.workspace
    if workspace:
        memberships = workspace.memberships.select_related("user").order_by("role", "user__username")
        return [membership.user for membership in memberships]
    if request_user and request_user.is_authenticated:
        return [request_user]
    return []


class PageReviewViewSet(SitePermissionMixin, viewsets.ModelViewSet):
    serializer_class = PageReviewSerializer
    site_lookup_field = "page__site"
    pagination_class = None

    def get_queryset(self):
        queryset = (
            PageReview.objects.select_related(
                "page",
                "page__site",
                "locale",
                "requested_by",
                "assigned_to",
                "approved_by",
            )
            .prefetch_related("comments__author", "comments__resolved_by", "comments__parent")
            .order_by("page__site__name", "page__title", "-updated_at")
        )
        site_id = self.request.query_params.get("site")
        page_id = self.request.query_params.get("page_id") or self.request.query_params.get("page")
        locale_id = self.request.query_params.get("locale")
        status_filter = self.request.query_params.get("status")
        assigned_to = self.request.query_params.get("assigned_to")
        if site_id:
            queryset = queryset.filter(page__site_id=site_id)
        if page_id:
            queryset = queryset.filter(page_id=page_id)
        if locale_id == "null":
            queryset = queryset.filter(locale__isnull=True)
        elif locale_id:
            queryset = queryset.filter(locale_id=locale_id)
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        if assigned_to:
            queryset = queryset.filter(assigned_to_id=assigned_to)
        return self.filter_by_site_permission(queryset)

    def perform_create(self, serializer):
        super().perform_create(serializer)

    def perform_update(self, serializer):
        super().perform_update(serializer)

    @action(detail=False, methods=["get"])
    def collaborators(self, request):
        site = self.get_site_from_request(key="site", source="query", require_edit=False)
        collaborators = _review_collaborators_for_site(site, request.user)
        serializer = CollaboratorUserSerializer(collaborators, many=True)
        return Response(serializer.data)

    def _transition_review(self, request, review: PageReview, next_status: str):
        serializer = self.get_serializer(review, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        now = timezone.now()
        save_kwargs = {"status": next_status}
        if next_status == PageReview.STATUS_IN_REVIEW:
            save_kwargs.update(
                {
                    "requested_by": request.user,
                    "requested_at": now,
                    "approved_by": None,
                    "approved_at": None,
                }
            )
        elif next_status == PageReview.STATUS_CHANGES_REQUESTED:
            save_kwargs.update(
                {
                    "responded_at": now,
                    "approved_by": None,
                    "approved_at": None,
                }
            )
        elif next_status == PageReview.STATUS_APPROVED:
            save_kwargs.update(
                {
                    "approved_by": request.user,
                    "approved_at": now,
                    "responded_at": now,
                }
            )
        elif next_status == PageReview.STATUS_DRAFT:
            save_kwargs.update(
                {
                    "approved_by": None,
                    "approved_at": None,
                    "responded_at": None,
                }
            )
        serializer.save(**save_kwargs)
        review.refresh_from_db()
        return Response(self.get_serializer(review).data)

    @action(detail=True, methods=["post"])
    def request_review(self, request, pk=None):
        return self._transition_review(request, self.get_object(), PageReview.STATUS_IN_REVIEW)

    @action(detail=True, methods=["post"])
    def request_changes(self, request, pk=None):
        return self._transition_review(request, self.get_object(), PageReview.STATUS_CHANGES_REQUESTED)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        return self._transition_review(request, self.get_object(), PageReview.STATUS_APPROVED)

    @action(detail=True, methods=["post"])
    def reopen(self, request, pk=None):
        return self._transition_review(request, self.get_object(), PageReview.STATUS_DRAFT)


class PageReviewCommentViewSet(SitePermissionMixin, viewsets.ModelViewSet):
    serializer_class = PageReviewCommentSerializer
    permission_classes = [permissions.IsAuthenticated]
    site_lookup_field = "review__page__site"
    pagination_class = None

    def get_queryset(self):
        queryset = (
            PageReviewComment.objects.select_related(
                "review",
                "review__page",
                "review__page__site",
                "author",
                "resolved_by",
                "parent",
            )
            .order_by("created_at")
        )
        site_id = self.request.query_params.get("site")
        review_id = self.request.query_params.get("review")
        page_id = self.request.query_params.get("page_id") or self.request.query_params.get("page")
        resolved = self.request.query_params.get("resolved")
        if site_id:
            queryset = queryset.filter(review__page__site_id=site_id)
        if review_id:
            queryset = queryset.filter(review_id=review_id)
        if page_id:
            queryset = queryset.filter(review__page_id=page_id)
        if resolved in {"1", "true", "yes"}:
            queryset = queryset.filter(is_resolved=True)
        elif resolved in {"0", "false", "no"}:
            queryset = queryset.filter(is_resolved=False)
        return self.filter_by_site_permission(queryset)

    def _apply_comment_resolution(self, comment: PageReviewComment, is_resolved: bool):
        updates = []
        if is_resolved:
            if not comment.is_resolved:
                comment.is_resolved = True
                updates.append("is_resolved")
            if not comment.resolved_by_id or not comment.resolved_at:
                comment.resolved_by = self.request.user
                comment.resolved_at = timezone.now()
                updates.extend(["resolved_by", "resolved_at", "updated_at"])
        else:
            if comment.is_resolved or comment.resolved_by_id or comment.resolved_at:
                comment.is_resolved = False
                comment.resolved_by = None
                comment.resolved_at = None
                updates.extend(["is_resolved", "resolved_by", "resolved_at", "updated_at"])
        if updates:
            comment.save(update_fields=updates)

    def perform_create(self, serializer):
        review = self.get_site_from_serializer(serializer)
        if review is None:
            raise ValidationError({"review": "A valid review is required."})
        self.check_site_edit_permission(review)
        comment = serializer.save(author=self.request.user)
        self._apply_comment_resolution(comment, serializer.validated_data.get("is_resolved", False))

    def perform_update(self, serializer):
        review = self.get_site_from_serializer(serializer)
        if review is None:
            raise ValidationError({"review": "A valid review is required."})
        self.check_site_edit_permission(review)
        comment = serializer.save()
        self._apply_comment_resolution(comment, comment.is_resolved)

    def perform_destroy(self, instance):
        self.check_site_edit_permission(instance.review.page.site)
        instance.delete()

    @action(detail=True, methods=["post"])
    def resolve(self, request, pk=None):
        comment = self.get_object()
        self._apply_comment_resolution(comment, True)
        return Response(self.get_serializer(comment).data)

    @action(detail=True, methods=["post"])
    def unresolve(self, request, pk=None):
        comment = self.get_object()
        self._apply_comment_resolution(comment, False)
        return Response(self.get_serializer(comment).data)


class PageRevisionViewSet(SitePermissionMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = PageRevisionSerializer

    def get_queryset(self):
        queryset = PageRevision.objects.select_related("page", "page__site").order_by("-created_at")
        page_id = self.request.query_params.get("page")
        site_id = self.request.query_params.get("site")
        if page_id:
            queryset = queryset.filter(page_id=page_id)
        if site_id:
            queryset = queryset.filter(page__site_id=site_id)
        return self.filter_by_site_permission(queryset)

    @action(detail=True, methods=["post"])
    def restore(self, request, pk=None):
        revision = self.get_object()
        page = revision.page
        try:
            normalized = normalize_page_content(
                title=page.title,
                slug=page.slug,
                path=page.path,
                is_homepage=page.is_homepage,
                status=Page.STATUS_DRAFT,
                locale_code="",
                builder_data=revision.snapshot or {},
                seo=page.seo,
                page_settings=page.page_settings,
                html=revision.html or "",
                css=revision.css or "",
                js=revision.js or "",
                schema_version=revision.builder_schema_version,
                strict=True,
            )
        except DjangoValidationError as exc:
            return Response(exc.message_dict if hasattr(exc, "message_dict") else {"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)
        page.builder_schema_version = normalized["schema_version"]
        page.builder_data = normalized["builder_data"]
        page.seo = normalized["seo"]
        page.page_settings = normalized["page_settings"]
        page.html = normalized["html"]
        page.css = normalized["css"]
        page.js = normalized["js"]
        page.status = Page.STATUS_DRAFT
        page.save(
            update_fields=[
                "builder_schema_version",
                "builder_data",
                "seo",
                "page_settings",
                "html",
                "css",
                "js",
                "status",
                "updated_at",
            ]
        )
        create_revision(page, f"Restored from {revision.label}")
        return Response(PageSerializer(page, context={"request": request}).data)


class MediaAssetViewSet(SitePermissionMixin, viewsets.ModelViewSet):
    serializer_class = MediaAssetSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_queryset(self):
        ensure_seed_data()
        queryset = MediaAsset.objects.select_related("site", "folder").order_by("-created_at")
        site_id = self.request.query_params.get("site")
        folder_id = self.request.query_params.get("folder")
        kind = self.request.query_params.get("kind")
        search = self.request.query_params.get("search")
        unfoldered = self.request.query_params.get("unfoldered")
        include_deleted = self.request.query_params.get("include_deleted")
        if site_id:
            queryset = queryset.filter(site_id=site_id)
        if folder_id:
            queryset = queryset.filter(folder_id=folder_id)
        if unfoldered in {"1", "true", "yes"}:
            queryset = queryset.filter(folder__isnull=True)
        if kind:
            queryset = queryset.filter(kind=kind)
        if include_deleted not in {"1", "true", "yes"}:
            queryset = queryset.filter(deleted_at__isnull=True)
        if search:
            queryset = queryset.filter(
                models.Q(title__icontains=search)
                | models.Q(alt_text__icontains=search)
                | models.Q(caption__icontains=search)
                | models.Q(tags__icontains=search)
            )
        return self.filter_by_site_permission(queryset)

    def _extract_media_metadata(self, uploaded_file) -> dict:
        metadata: dict[str, object] = {}
        if uploaded_file is None:
            return metadata

        content_type = getattr(uploaded_file, "content_type", "") or ""
        if content_type:
            metadata["content_type"] = content_type

        if hasattr(uploaded_file, "size"):
            metadata["size"] = int(uploaded_file.size or 0)

        head = b""
        current_pos = None
        if hasattr(uploaded_file, "tell"):
            try:
                current_pos = uploaded_file.tell()
            except Exception:
                current_pos = None
        try:
            if hasattr(uploaded_file, "seek"):
                uploaded_file.seek(0)
            head = uploaded_file.read(1024 * 1024) or b""
            if isinstance(head, str):
                head = head.encode("utf-8", errors="ignore")
        except Exception:
            head = b""
        finally:
            if hasattr(uploaded_file, "seek"):
                try:
                    if current_pos is not None:
                        uploaded_file.seek(current_pos)
                    else:
                        uploaded_file.seek(0)
                except Exception:
                    pass

        if head:
            metadata["content_signature"] = hashlib.sha256(head).hexdigest()

        try:
            from PIL import Image

            with Image.open(uploaded_file) as image:
                metadata["image_width"] = int(image.width)
                metadata["image_height"] = int(image.height)
                metadata["image_format"] = str(image.format or "").lower()
        except Exception:
            pass
        return metadata

    def _save_security_metadata(self, asset: MediaAsset, uploaded_file=None):
        source_file = uploaded_file or asset.file
        if not source_file:
            return
        extracted = self._extract_media_metadata(source_file)
        dirty_fields: list[str] = []

        content_type = str(extracted.get("content_type") or "")
        if content_type and asset.mime_type != content_type:
            asset.mime_type = content_type
            dirty_fields.append("mime_type")

        file_size = int(extracted.get("size") or 0)
        if file_size and asset.file_size != file_size:
            asset.file_size = file_size
            dirty_fields.append("file_size")

        signature = str(extracted.get("content_signature") or "")
        if signature and asset.content_signature != signature:
            asset.content_signature = signature
            dirty_fields.append("content_signature")

        metadata = asset.metadata if isinstance(asset.metadata, dict) else {}
        merged_metadata = {**metadata, **{k: v for k, v in extracted.items() if k not in {"content_type", "size", "content_signature"}}}
        if merged_metadata != metadata:
            asset.metadata = merged_metadata
            dirty_fields.append("metadata")

        if dirty_fields:
            dirty_fields.append("updated_at")
            asset.save(update_fields=dirty_fields)

    def perform_create(self, serializer):
        asset = super().perform_create(serializer)
        self._save_security_metadata(asset, uploaded_file=self.request.FILES.get("file"))
        queue_search_index("media", asset.id)
        trigger_webhooks(asset.site, "media.asset.created", {"asset_id": asset.id, "title": asset.title})

    def perform_update(self, serializer):
        asset = super().perform_update(serializer)
        self._save_security_metadata(asset, uploaded_file=self.request.FILES.get("file"))
        queue_search_index("media", asset.id)
        trigger_webhooks(asset.site, "media.asset.updated", {"asset_id": asset.id, "title": asset.title})

    def create(self, request, *args, **kwargs):
        """Override create to add file validation."""
        from .upload_validation import validate_upload

        file = request.FILES.get("file")
        if file:
            valid, error, kind = validate_upload(file)
            if not valid:
                return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
            # Set kind in request data if not provided
            if "kind" not in request.data:
                if hasattr(request.data, "_mutable"):
                    was_mutable = request.data._mutable
                    request.data._mutable = True
                    request.data["kind"] = kind
                    request.data._mutable = was_mutable
                else:
                    request.data["kind"] = kind

        return super().create(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        asset = self.get_object()
        if asset.deleted_at is None:
            asset.deleted_at = timezone.now()
            if request.user.is_authenticated:
                asset.deleted_by = request.user
            asset.save(update_fields=["deleted_at", "deleted_by", "updated_at"])
            queue_search_index("media", asset.id, operation="delete")
            trigger_webhooks(asset.site, "media.asset.deleted", {"asset_id": asset.id, "title": asset.title})
        serializer = self.get_serializer(asset)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=False, methods=["post"])
    def bulk_delete(self, request):
        ids = request.data.get("ids", [])
        if not ids:
            return Response({"detail": "Provide 'ids' list."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            normalized_ids = [int(item) for item in ids]
        except (TypeError, ValueError):
            return Response({"detail": "All ids must be integers."}, status=status.HTTP_400_BAD_REQUEST)

        assets = self.filter_by_site_permission(MediaAsset.objects.filter(pk__in=normalized_ids))
        if assets.count() != len(set(normalized_ids)):
            return Response(
                {"detail": "You don't have permission to delete one or more selected assets."},
                status=status.HTTP_403_FORBIDDEN,
            )

        now = timezone.now()
        deleted_count = 0
        for asset in assets:
            if asset.deleted_at is None:
                asset.deleted_at = now
                if request.user.is_authenticated:
                    asset.deleted_by = request.user
                asset.save(update_fields=["deleted_at", "deleted_by", "updated_at"])
                queue_search_index("media", asset.id, operation="delete")
                deleted_count += 1
        return Response({"deleted": deleted_count})

    @action(detail=True, methods=["post"])
    def restore(self, request, pk=None):
        asset = self.get_object()
        if asset.deleted_at is None:
            return Response(MediaAssetSerializer(asset, context={"request": request}).data)
        asset.deleted_at = None
        asset.deleted_by = None
        asset.save(update_fields=["deleted_at", "deleted_by", "updated_at"])
        queue_search_index("media", asset.id)
        trigger_webhooks(asset.site, "media.asset.restored", {"asset_id": asset.id, "title": asset.title})
        return Response(MediaAssetSerializer(asset, context={"request": request}).data)

    @action(detail=False, methods=["post"])
    def bulk_restore(self, request):
        ids = request.data.get("ids", [])
        if not ids:
            return Response({"detail": "Provide 'ids' list."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            normalized_ids = [int(item) for item in ids]
        except (TypeError, ValueError):
            return Response({"detail": "All ids must be integers."}, status=status.HTTP_400_BAD_REQUEST)

        assets = self.filter_by_site_permission(MediaAsset.objects.filter(pk__in=normalized_ids))
        restored = 0
        for asset in assets:
            if asset.deleted_at is not None:
                asset.deleted_at = None
                asset.deleted_by = None
                asset.save(update_fields=["deleted_at", "deleted_by", "updated_at"])
                queue_search_index("media", asset.id)
                restored += 1
        return Response({"restored": restored})

    @action(detail=True, methods=["delete"])
    def hard_delete(self, request, pk=None):
        asset = self.get_object()
        try:
            asset.file.delete(save=False)
        except Exception:
            pass
        asset_id = asset.id
        asset.delete()
        queue_search_index("media", asset_id, operation="delete")
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=["post"])
    def move_to_folder(self, request):
        ids = request.data.get("ids", [])
        folder_id = request.data.get("folder_id")
        if not ids:
            return Response({"detail": "Provide 'ids' list."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            normalized_ids = [int(item) for item in ids]
        except (TypeError, ValueError):
            return Response({"detail": "All ids must be integers."}, status=status.HTTP_400_BAD_REQUEST)

        assets = self.filter_by_site_permission(MediaAsset.objects.filter(pk__in=normalized_ids))
        if assets.count() != len(set(normalized_ids)):
            return Response(
                {"detail": "You don't have permission to move one or more selected assets."},
                status=status.HTTP_403_FORBIDDEN,
            )

        folder = None
        if folder_id:
            folder = get_object_or_404(self.filter_by_site_permission(MediaFolder.objects.all()), pk=folder_id)
            if assets.exclude(site_id=folder.site_id).exists():
                return Response(
                    {"detail": "Assets can only be moved to a folder in the same site."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        updated = assets.update(folder=folder)
        return Response({"moved": updated})

    @action(detail=True, methods=["get"])
    def usage_references(self, request, pk=None):
        asset = self.get_object()
        references = asset.usage_references.order_by("-updated_at")
        serializer = AssetUsageReferenceSerializer(references, many=True, context={"request": request})
        return Response(serializer.data)

    @action(detail=True, methods=["post"])
    def upsert_usage_reference(self, request, pk=None):
        asset = self.get_object()
        payload = {
            "site": asset.site_id,
            "asset": asset.id,
            "entity_type": request.data.get("entity_type"),
            "entity_id": request.data.get("entity_id"),
            "field_name": request.data.get("field_name") or "",
            "metadata": request.data.get("metadata") or {},
        }
        existing = AssetUsageReference.objects.filter(
            asset=asset,
            entity_type=payload["entity_type"],
            entity_id=payload["entity_id"],
            field_name=payload["field_name"],
        ).first()
        serializer = AssetUsageReferenceSerializer(existing, data=payload, context={"request": request})
        serializer.is_valid(raise_exception=True)
        reference = serializer.save()
        return Response(AssetUsageReferenceSerializer(reference, context={"request": request}).data)


class AssetUsageReferenceViewSet(SitePermissionMixin, viewsets.ModelViewSet):
    serializer_class = AssetUsageReferenceSerializer

    def get_queryset(self):
        queryset = AssetUsageReference.objects.select_related("site", "asset").order_by("-updated_at")
        site_id = self.request.query_params.get("site")
        asset_id = self.request.query_params.get("asset")
        entity_type = self.request.query_params.get("entity_type")
        if site_id:
            queryset = queryset.filter(site_id=site_id)
        if asset_id:
            queryset = queryset.filter(asset_id=asset_id)
        if entity_type:
            queryset = queryset.filter(entity_type=entity_type)
        return self.filter_by_site_permission(queryset)


class PostCategoryViewSet(SitePermissionMixin, viewsets.ModelViewSet):
    serializer_class = PostCategorySerializer

    def get_queryset(self):
        ensure_seed_data()
        queryset = PostCategory.objects.select_related("site").order_by("name")
        site_id = self.request.query_params.get("site")
        if site_id:
            queryset = queryset.filter(site_id=site_id)
        return self.filter_by_site_permission(queryset)


class PostTagViewSet(SitePermissionMixin, viewsets.ModelViewSet):
    serializer_class = PostTagSerializer

    def get_queryset(self):
        ensure_seed_data()
        queryset = PostTag.objects.select_related("site").order_by("name")
        site_id = self.request.query_params.get("site")
        if site_id:
            queryset = queryset.filter(site_id=site_id)
        return self.filter_by_site_permission(queryset)


class BlogAuthorViewSet(SitePermissionMixin, viewsets.ModelViewSet):
    serializer_class = BlogAuthorSerializer

    def get_queryset(self):
        ensure_seed_data()
        queryset = BlogAuthor.objects.select_related("site", "user").order_by("display_name")
        site_id = self.request.query_params.get("site")
        active = self.request.query_params.get("active")
        if site_id:
            queryset = queryset.filter(site_id=site_id)
        if active in {"1", "true", "yes"}:
            queryset = queryset.filter(is_active=True)
        elif active in {"0", "false", "no"}:
            queryset = queryset.filter(is_active=False)
        return self.filter_by_site_permission(queryset)


class ProductCategoryViewSet(SitePermissionMixin, viewsets.ModelViewSet):
    serializer_class = ProductCategorySerializer

    def get_queryset(self):
        ensure_seed_data()
        queryset = ProductCategory.objects.select_related("site").order_by("name")
        site_id = self.request.query_params.get("site")
        if site_id:
            queryset = queryset.filter(site_id=site_id)
        return self.filter_by_site_permission(queryset)


class DiscountCodeViewSet(SitePermissionMixin, viewsets.ModelViewSet):
    serializer_class = DiscountCodeSerializer

    def get_queryset(self):
        ensure_seed_data()
        queryset = DiscountCode.objects.select_related("site").order_by("code")
        site_id = self.request.query_params.get("site")
        active = self.request.query_params.get("active")
        if site_id:
            queryset = queryset.filter(site_id=site_id)
        if active in {"true", "1", "yes"}:
            queryset = queryset.filter(active=True)
        elif active in {"false", "0", "no"}:
            queryset = queryset.filter(active=False)
        return self.filter_by_site_permission(queryset)


class ShippingZoneViewSet(SitePermissionMixin, viewsets.ModelViewSet):
    serializer_class = ShippingZoneSerializer

    def get_queryset(self):
        ensure_seed_data()
        queryset = ShippingZone.objects.select_related("site").prefetch_related("rates").order_by("name")
        site_id = self.request.query_params.get("site")
        active = self.request.query_params.get("active")
        if site_id:
            queryset = queryset.filter(site_id=site_id)
        if active in {"true", "1", "yes"}:
            queryset = queryset.filter(active=True)
        elif active in {"false", "0", "no"}:
            queryset = queryset.filter(active=False)
        return self.filter_by_site_permission(queryset)


class ShippingRateViewSet(SitePermissionMixin, viewsets.ModelViewSet):
    serializer_class = ShippingRateSerializer
    site_lookup_field = "zone__site"

    def get_queryset(self):
        ensure_seed_data()
        queryset = ShippingRate.objects.select_related("zone", "zone__site").order_by("price", "id")
        site_id = self.request.query_params.get("site")
        zone_id = self.request.query_params.get("zone")
        if site_id:
            queryset = queryset.filter(zone__site_id=site_id)
        if zone_id:
            queryset = queryset.filter(zone_id=zone_id)
        return self.filter_by_site_permission(queryset)


class TaxRateViewSet(SitePermissionMixin, viewsets.ModelViewSet):
    serializer_class = TaxRateSerializer

    def get_queryset(self):
        ensure_seed_data()
        queryset = TaxRate.objects.select_related("site").order_by("name")
        site_id = self.request.query_params.get("site")
        active = self.request.query_params.get("active")
        if site_id:
            queryset = queryset.filter(site_id=site_id)
        if active in {"true", "1", "yes"}:
            queryset = queryset.filter(active=True)
        elif active in {"false", "0", "no"}:
            queryset = queryset.filter(active=False)
        return self.filter_by_site_permission(queryset)


class PostViewSet(SitePermissionMixin, viewsets.ModelViewSet):
    serializer_class = PostSerializer

    def get_queryset(self):
        ensure_seed_data()
        queryset = (
            Post.objects.select_related("site", "featured_media", "primary_author")
            .prefetch_related("categories", "tags", "comments", "related_posts")
            .order_by("-published_at", "-updated_at")
        )
        site_id = self.request.query_params.get("site")
        status_filter = self.request.query_params.get("status")
        if site_id:
            queryset = queryset.filter(site_id=site_id)
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        return self.filter_by_site_permission(queryset)

    def perform_create(self, serializer):
        post = super().perform_create(serializer)
        queue_search_index("post", post.id)

    def perform_update(self, serializer):
        post = super().perform_update(serializer)
        queue_search_index("post", post.id)
        trigger_webhooks(post.site, "post.updated", {"post_id": post.id, "title": post.title, "slug": post.slug})

    @action(detail=True, methods=["post"])
    def publish(self, request, pk=None):
        post = self.get_object()
        post.status = Post.STATUS_PUBLISHED
        post.published_at = timezone.now()
        post.scheduled_at = None
        post.save(update_fields=["status", "published_at", "scheduled_at", "updated_at"])
        create_publish_snapshot(
            site=post.site,
            target_type=PublishSnapshot.TARGET_POST,
            target_id=post.id,
            instance=post,
            actor=request.user,
            revision_label="Published snapshot",
            metadata={"source": "builder.post.publish"},
        )
        queue_search_index("post", post.id)
        trigger_webhooks(post.site, "post.published", {"post_id": post.id, "title": post.title, "slug": post.slug})
        trigger_webhooks(
            post.site,
            "site.published",
            {"site_id": post.site_id, "source": "post", "post_id": post.id, "slug": post.slug},
        )
        return Response(PostSerializer(post, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def unpublish(self, request, pk=None):
        post = self.get_object()
        post.status = Post.STATUS_DRAFT
        post.scheduled_at = None
        post.save(update_fields=["status", "scheduled_at", "updated_at"])
        create_publish_snapshot(
            site=post.site,
            target_type=PublishSnapshot.TARGET_POST,
            target_id=post.id,
            instance=post,
            actor=request.user,
            revision_label="Unpublished snapshot",
            metadata={"source": "builder.post.unpublish"},
        )
        queue_search_index("post", post.id)
        return Response(PostSerializer(post, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def schedule(self, request, pk=None):
        """Schedule a post for future publishing."""
        post = self.get_object()
        scheduled_at = request.data.get("scheduled_at")
        if not scheduled_at:
            return Response({"detail": "scheduled_at is required"}, status=status.HTTP_400_BAD_REQUEST)

        from dateutil.parser import parse as parse_date
        try:
            scheduled_time = parse_date(scheduled_at)
        except (ValueError, TypeError):
            return Response({"detail": "Invalid date format"}, status=status.HTTP_400_BAD_REQUEST)

        post.scheduled_at = scheduled_time
        post.status = Post.STATUS_SCHEDULED
        post.save(update_fields=["scheduled_at", "status", "updated_at"])

        from .jobs import schedule_content_publish
        schedule_content_publish("post", post.id, scheduled_time)

        return Response(PostSerializer(post, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def submit_for_review(self, request, pk=None):
        post = self.get_object()
        post.status = Post.STATUS_IN_REVIEW
        post.save(update_fields=["status", "updated_at"])
        trigger_webhooks(post.site, "post.review_requested", {"post_id": post.id, "title": post.title, "slug": post.slug})
        return Response(PostSerializer(post, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def archive(self, request, pk=None):
        post = self.get_object()
        post.status = Post.STATUS_ARCHIVED
        post.save(update_fields=["status", "updated_at"])
        trigger_webhooks(post.site, "post.archived", {"post_id": post.id, "title": post.title, "slug": post.slug})
        return Response(PostSerializer(post, context={"request": request}).data)


class ProductViewSet(SitePermissionMixin, viewsets.ModelViewSet):
    serializer_class = ProductSerializer

    def get_queryset(self):
        ensure_seed_data()
        queryset = (
            Product.objects.select_related("site", "featured_media")
            .prefetch_related("categories", "variants")
            .order_by("-is_featured", "-published_at", "title")
        )
        site_id = self.request.query_params.get("site")
        status_filter = self.request.query_params.get("status")
        search = (self.request.query_params.get("search") or "").strip()
        if site_id:
            queryset = queryset.filter(site_id=site_id)
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        if search:
            queryset = queryset.filter(
                models.Q(title__icontains=search)
                | models.Q(slug__icontains=search)
                | models.Q(excerpt__icontains=search)
                | models.Q(description_html__icontains=search)
                | models.Q(categories__name__icontains=search)
                | models.Q(variants__sku__icontains=search)
            ).distinct()
        return self.filter_by_site_permission(queryset)

    def perform_create(self, serializer):
        product = super().perform_create(serializer)
        queue_search_index("product", product.id)

    def perform_update(self, serializer):
        product = super().perform_update(serializer)
        queue_search_index("product", product.id)
        trigger_webhooks(product.site, "product.updated", {"product_id": product.id, "title": product.title, "slug": product.slug})

    @action(detail=True, methods=["post"])
    def publish(self, request, pk=None):
        product = self.get_object()
        product.status = Product.STATUS_PUBLISHED
        product.published_at = timezone.now()
        product.save(update_fields=["status", "published_at", "updated_at"])
        create_publish_snapshot(
            site=product.site,
            target_type=PublishSnapshot.TARGET_PRODUCT,
            target_id=product.id,
            instance=product,
            actor=request.user,
            revision_label="Published snapshot",
            metadata={"source": "builder.product.publish"},
        )
        queue_search_index("product", product.id)
        trigger_webhooks(
            product.site,
            "product.published",
            {"product_id": product.id, "title": product.title, "slug": product.slug},
        )
        trigger_webhooks(
            product.site,
            "site.published",
            {"site_id": product.site_id, "source": "product", "product_id": product.id, "slug": product.slug},
        )
        return Response(ProductSerializer(product, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def unpublish(self, request, pk=None):
        product = self.get_object()
        product.status = Product.STATUS_DRAFT
        product.save(update_fields=["status", "updated_at"])
        create_publish_snapshot(
            site=product.site,
            target_type=PublishSnapshot.TARGET_PRODUCT,
            target_id=product.id,
            instance=product,
            actor=request.user,
            revision_label="Unpublished snapshot",
            metadata={"source": "builder.product.unpublish"},
        )
        queue_search_index("product", product.id)
        return Response(ProductSerializer(product, context={"request": request}).data)


class ProductVariantViewSet(SitePermissionMixin, viewsets.ModelViewSet):
    serializer_class = ProductVariantSerializer
    site_lookup_field = "product__site"

    def get_queryset(self):
        ensure_seed_data()
        queryset = ProductVariant.objects.select_related("product", "product__site").order_by("-is_default", "title")
        site_id = self.request.query_params.get("site")
        product_id = self.request.query_params.get("product")
        if site_id:
            queryset = queryset.filter(product__site_id=site_id)
        if product_id:
            queryset = queryset.filter(product_id=product_id)
        return self.filter_by_site_permission(queryset)


class CommentViewSet(SitePermissionMixin, viewsets.ModelViewSet):
    serializer_class = CommentSerializer
    site_lookup_field = "post__site"

    def get_queryset(self):
        ensure_seed_data()
        queryset = Comment.objects.select_related("post", "post__site").order_by("-created_at")
        post_id = self.request.query_params.get("post")
        site_id = self.request.query_params.get("site")
        if post_id:
            queryset = queryset.filter(post_id=post_id)
        if site_id:
            queryset = queryset.filter(post__site_id=site_id)
        return self.filter_by_site_permission(queryset)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        comment = self.get_object()
        comment.is_approved = True
        comment.moderation_state = Comment.MODERATION_APPROVED
        comment.save(update_fields=["is_approved", "moderation_state", "updated_at"])
        return Response(CommentSerializer(comment, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        comment = self.get_object()
        comment.is_approved = False
        comment.moderation_state = Comment.MODERATION_REJECTED
        comment.moderation_notes = (request.data.get("reason") or comment.moderation_notes or "")[:1000]
        comment.save(update_fields=["is_approved", "moderation_state", "moderation_notes", "updated_at"])
        return Response(CommentSerializer(comment, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def mark_spam(self, request, pk=None):
        comment = self.get_object()
        comment.is_approved = False
        comment.moderation_state = Comment.MODERATION_SPAM
        comment.flagged_at = timezone.now()
        score = request.data.get("spam_score")
        provider = request.data.get("spam_provider")
        notes = request.data.get("reason")
        try:
            if score is not None:
                comment.spam_score = float(score)
        except (TypeError, ValueError):
            pass
        if provider is not None:
            comment.spam_provider = str(provider)[:80]
        if notes:
            comment.moderation_notes = str(notes)[:1000]
        comment.save(
            update_fields=[
                "is_approved",
                "moderation_state",
                "flagged_at",
                "spam_score",
                "spam_provider",
                "moderation_notes",
                "updated_at",
            ]
        )
        trigger_webhooks(
            comment.post.site,
            "comment.spam_flagged",
            {"post_id": comment.post_id, "comment_id": comment.id, "spam_score": comment.spam_score},
        )
        return Response(CommentSerializer(comment, context={"request": request}).data)


class FormSubmissionViewSet(SitePermissionMixin, viewsets.ModelViewSet):
    serializer_class = FormSubmissionSerializer

    def get_queryset(self):
        ensure_seed_data()
        queryset = FormSubmission.objects.select_related("site", "page").order_by("-created_at")
        site_id = self.request.query_params.get("site")
        if site_id:
            queryset = queryset.filter(site_id=site_id)
        return self.filter_by_site_permission(queryset)


class CartViewSet(SitePermissionMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = CartSerializer

    def get_queryset(self):
        ensure_seed_data()
        queryset = (
            Cart.objects.select_related("site")
            .prefetch_related("items__product_variant__product")
            .order_by("-updated_at")
        )
        site_id = self.request.query_params.get("site")
        status_filter = self.request.query_params.get("status")
        if site_id:
            queryset = queryset.filter(site_id=site_id)
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        return self.filter_by_site_permission(queryset)


class OrderViewSet(SitePermissionMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = OrderSerializer

    def get_queryset(self):
        ensure_seed_data()
        queryset = (
            Order.objects.select_related("site")
            .prefetch_related("items__product", "items__product_variant")
            .order_by("-placed_at")
        )
        site_id = self.request.query_params.get("site")
        status_filter = self.request.query_params.get("status")
        payment_status = self.request.query_params.get("payment_status")
        search = (self.request.query_params.get("search") or "").strip()
        if site_id:
            queryset = queryset.filter(site_id=site_id)
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        if payment_status:
            queryset = queryset.filter(payment_status=payment_status)
        if search:
            queryset = queryset.filter(
                models.Q(order_number__icontains=search)
                | models.Q(customer_name__icontains=search)
                | models.Q(customer_email__icontains=search)
            )
        return self.filter_by_site_permission(queryset)

    @action(detail=True, methods=["post"])
    def mark_paid(self, request, pk=None):
        order = self.get_object()
        order.payment_status = Order.PAYMENT_PAID
        order.status = Order.STATUS_PAID
        order.save(update_fields=["payment_status", "status", "updated_at"])
        return Response(OrderSerializer(order, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def fulfill(self, request, pk=None):
        order = self.get_object()
        order.status = Order.STATUS_FULFILLED
        order.save(update_fields=["status", "updated_at"])
        return Response(OrderSerializer(order, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        order = self.get_object()
        order.status = Order.STATUS_CANCELLED
        order.payment_status = Order.PAYMENT_FAILED
        order.save(update_fields=["status", "payment_status", "updated_at"])
        return Response(OrderSerializer(order, context={"request": request}).data)


class PublicFormSubmissionView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = []  # Throttle applied via get_throttles

    def get_throttles(self):
        from .throttles import PublicFormThrottle
        return [PublicFormThrottle()]

    def post(self, request):
        ensure_seed_data()
        serializer = PublicFormSubmissionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        site = get_object_or_404(Site, slug=serializer.validated_data["site_slug"])
        raw_page_path = serializer.validated_data.get("page_path", "")
        page, translation, locale, normalized_path = resolve_public_page_context(site, raw_page_path)
        if not page:
            page = site.pages.filter(is_homepage=True).first()

        submission = FormSubmission.objects.create(
            site=site,
            page=page,
            form_name=serializer.validated_data["form_name"],
            payload=sanitize_json_payload(serializer.validated_data["payload"]),
        )
        record_conversion_from_assignments(
            request,
            site=site,
            page=page,
            locale=translation.locale if translation else locale,
            form_name=submission.form_name,
            request_path=normalized_path,
            metadata={"source": "legacy_public_form_submit"},
        )
        trigger_webhooks(site, "form.submitted", {"submission_id": submission.id, "form_name": submission.form_name, "payload": submission.payload})
        return Response(FormSubmissionSerializer(submission, context={"request": request}).data, status=status.HTTP_201_CREATED)


class PublicCommentSubmissionView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = []

    def get_throttles(self):
        from .throttles import PublicCommentThrottle
        return [PublicCommentThrottle()]

    def post(self, request):
        ensure_seed_data()
        serializer = PublicCommentSubmissionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        site = get_object_or_404(Site, slug=serializer.validated_data["site_slug"])
        post = get_object_or_404(site.posts.all(), slug=serializer.validated_data["post_slug"])
        spam_result = evaluate_comment_spam(
            author_email=serializer.validated_data["author_email"],
            body=serializer.validated_data["body"],
        )
        comment = Comment.objects.create(
            post=post,
            author_name=sanitize_text(serializer.validated_data["author_name"], max_length=140),
            author_email=serializer.validated_data["author_email"],
            body=sanitize_text(serializer.validated_data["body"], max_length=5000),
            is_approved=not spam_result.is_spam,
            moderation_state=Comment.MODERATION_SPAM if spam_result.is_spam else Comment.MODERATION_PENDING,
            spam_score=spam_result.score,
            spam_provider=spam_result.provider,
            flagged_at=timezone.now() if spam_result.is_spam else None,
        )
        trigger_webhooks(
            post.site,
            "comment.submitted",
            {
                "comment_id": comment.id,
                "post_id": post.id,
                "status": comment.moderation_state,
                "spam_score": comment.spam_score,
                "spam_provider": comment.spam_provider,
            },
        )
        return Response(
            {
                "id": comment.id,
                "detail": "Comment received and queued for moderation.",
                "status": comment.moderation_state,
            },
            status=status.HTTP_201_CREATED,
        )


def _shop_checkout_session_key(site_slug: str) -> str:
    """Return site-scoped session key for checkout state."""
    return f"wb_shop_checkout:{site_slug}"


def _shop_order_session_key(site_slug: str) -> str:
    """Return site-scoped session key for order access."""
    return f"wb_shop_orders:{site_slug}"


def _remember_checkout_order(request, order: Order) -> None:
    """Remember order ID in session for access control, scoped by site."""
    key = _shop_order_session_key(order.site.slug)
    order_ids = request.session.get(key, [])
    if order.id not in order_ids:
        request.session[key] = [*order_ids, order.id][-20:]
        request.session.modified = True


def _can_access_checkout_order(request, order: Order, *, require_manage: bool = False) -> bool:
    from .workspace_views import check_site_manage_permission, check_site_permission

    if request.user.is_authenticated:
        if require_manage:
            return check_site_manage_permission(request.user, order.site)
        return check_site_permission(request.user, order.site, require_edit=True)
    if require_manage:
        return False
    # Check site-scoped session key for order access
    key = _shop_order_session_key(order.site.slug)
    return order.id in request.session.get(key, [])


def _check_checkout_order_access(request, order: Order, *, require_manage: bool = False) -> None:
    if not _can_access_checkout_order(request, order, require_manage=require_manage):
        raise PermissionDenied("You don't have permission to access this order.")


def _shop_catalog_queryset(site: Site, *, search: str = "", category_slug: str = "", sort: str = ""):
    queryset = (
        site.products.filter(status=Product.STATUS_PUBLISHED)
        .select_related("featured_media")
        .prefetch_related("categories", "variants")
        .annotate(min_price=models.Min("variants__price", filter=models.Q(variants__is_active=True)))
        .distinct()
    )

    if search:
        queryset = queryset.filter(
            models.Q(title__icontains=search)
            | models.Q(slug__icontains=search)
            | models.Q(excerpt__icontains=search)
            | models.Q(description_html__icontains=search)
            | models.Q(categories__name__icontains=search)
            | models.Q(variants__sku__icontains=search)
        ).distinct()

    if category_slug:
        queryset = queryset.filter(categories__slug=category_slug)

    sort_map = {
        "price_asc": ["min_price", "title"],
        "price_desc": ["-min_price", "title"],
        "title_asc": ["title"],
        "title_desc": ["-title"],
        "newest": ["-published_at", "-is_featured", "title"],
    }
    return queryset.order_by(*(sort_map.get(sort) or ["-is_featured", "-published_at", "title"]))


def _get_shop_checkout_state(request, site_slug: str) -> dict:
    """Get checkout state from site-scoped session key."""
    key = _shop_checkout_session_key(site_slug)
    return dict(request.session.get(key) or {})


def _set_shop_checkout_state(request, site_slug: str, state: dict) -> None:
    """Set checkout state in site-scoped session key."""
    key = _shop_checkout_session_key(site_slug)
    request.session[key] = state
    request.session.modified = True


def _shop_pricing_payload(request, site_slug: str) -> dict:
    checkout_state = _get_shop_checkout_state(request, site_slug)
    shipping_country = str(
        request.POST.get("shipping_country")
        or request.GET.get("country")
        or checkout_state.get("shipping_country")
        or ""
    ).strip().upper()
    shipping_state = str(
        request.POST.get("shipping_state")
        or request.GET.get("state")
        or checkout_state.get("shipping_state")
        or ""
    ).strip().upper()
    discount_code = str(
        request.POST.get("discount_code")
        or request.GET.get("discount")
        or checkout_state.get("discount_code")
        or ""
    ).strip().upper()
    raw_shipping_rate_id = (
        request.POST.get("shipping_rate_id")
        or request.GET.get("shipping_rate_id")
        or checkout_state.get("shipping_rate_id")
        or ""
    )
    try:
        shipping_rate_id = int(raw_shipping_rate_id) if raw_shipping_rate_id else None
    except (TypeError, ValueError):
        shipping_rate_id = None

    state = {
        "shipping_country": shipping_country,
        "shipping_state": shipping_state,
        "discount_code": discount_code,
        "shipping_rate_id": shipping_rate_id,
    }
    _set_shop_checkout_state(request, site_slug, state)
    return {
        "shipping_address": {
            "country": shipping_country,
            "state": shipping_state,
        },
        "shipping_rate_id": shipping_rate_id,
        "discount_code": discount_code,
        "checkout_state": state,
    }


class PublicProductListView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, site_slug: str):
        ensure_seed_data()
        site = get_object_or_404(Site, slug=site_slug)
        search = (request.query_params.get("q") or "").strip()
        category_slug = (request.query_params.get("category") or "").strip()
        sort = (request.query_params.get("sort") or "").strip()
        queryset = _shop_catalog_queryset(site, search=search, category_slug=category_slug, sort=sort)
        if request.query_params.get("featured") in {"1", "true", "yes"}:
            queryset = queryset.filter(is_featured=True)
        return Response(ProductSerializer(queryset, many=True, context={"request": request}).data)


class PublicProductDetailView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, site_slug: str, product_slug: str):
        ensure_seed_data()
        site = get_object_or_404(Site, slug=site_slug)
        product = get_object_or_404(
            site.products.select_related("featured_media").prefetch_related("categories", "variants"),
            slug=product_slug,
            status=Product.STATUS_PUBLISHED,
        )
        return Response(ProductSerializer(product, context={"request": request}).data)


class PublicCartView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, site_slug: str):
        ensure_seed_data()
        site = get_object_or_404(Site, slug=site_slug)
        cart = get_or_create_cart(site, request.session)
        return Response(CartSerializer(cart, context={"request": request}).data)


class PublicCartPricingView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request, site_slug: str):
        ensure_seed_data()
        site = get_object_or_404(Site, slug=site_slug)
        serializer = PublicCartPricingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        cart = get_or_create_cart(site, request.session)
        try:
            pricing = calculate_cart_pricing(
                cart,
                shipping_address=serializer.validated_data.get("shipping_address") or {},
                shipping_rate_id=serializer.validated_data.get("shipping_rate_id"),
                discount_code=serializer.validated_data.get("discount_code", ""),
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        pricing.pop("discount_code_obj", None)
        return Response(
            {
                "cart": CartSerializer(cart, context={"request": request}).data,
                "pricing": pricing,
            }
        )


class PublicCartItemsView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request, site_slug: str):
        ensure_seed_data()
        site = get_object_or_404(Site, slug=site_slug)
        serializer = PublicCartAddSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        product = get_object_or_404(site.products.all(), slug=serializer.validated_data["product_slug"], status=Product.STATUS_PUBLISHED)
        try:
            variant = resolve_variant(product, serializer.validated_data.get("variant_id"))
        except ProductVariant.DoesNotExist:
            return Response({"detail": "Selected variant is not available."}, status=status.HTTP_400_BAD_REQUEST)

        cart = get_or_create_cart(site, request.session)
        quantity = serializer.validated_data["quantity"]
        cart_item, created = CartItem.objects.get_or_create(
            cart=cart,
            product_variant=variant,
            defaults={"quantity": quantity},
        )
        if not created:
            cart_item.quantity += quantity

        try:
            ensure_variant_inventory(variant, cart_item.quantity)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        sync_cart_item(cart_item)
        cart_item.save()
        cart = recalculate_cart(cart)
        return Response(
            CartSerializer(cart, context={"request": request}).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class PublicCartItemDetailView(APIView):
    permission_classes = [permissions.AllowAny]

    def patch(self, request, site_slug: str, item_id: int):
        ensure_seed_data()
        site = get_object_or_404(Site, slug=site_slug)
        serializer = PublicCartItemUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        cart = get_or_create_cart(site, request.session)
        cart_item = get_object_or_404(cart.items.select_related("product_variant", "product_variant__product"), pk=item_id)
        quantity = serializer.validated_data["quantity"]
        if quantity == 0:
            cart_item.delete()
        else:
            try:
                ensure_variant_inventory(cart_item.product_variant, quantity)
            except ValueError as exc:
                return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
            cart_item.quantity = quantity
            sync_cart_item(cart_item)
            cart_item.save()

        cart = recalculate_cart(cart)
        return Response(CartSerializer(cart, context={"request": request}).data)

    def delete(self, request, site_slug: str, item_id: int):
        ensure_seed_data()
        site = get_object_or_404(Site, slug=site_slug)
        cart = get_or_create_cart(site, request.session)
        cart_item = get_object_or_404(cart.items.all(), pk=item_id)
        cart_item.delete()
        cart = recalculate_cart(cart)
        return Response(CartSerializer(cart, context={"request": request}).data)


class PublicCheckoutView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = []

    def get_throttles(self):
        from .throttles import PublicCheckoutThrottle
        return [PublicCheckoutThrottle()]

    def post(self, request, site_slug: str):
        ensure_seed_data()
        site = get_object_or_404(Site, slug=site_slug)
        serializer = PublicCheckoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        cart = get_or_create_cart(site, request.session)

        try:
            order = create_order_from_cart(
                cart,
                customer_name=serializer.validated_data["customer_name"],
                customer_email=serializer.validated_data["customer_email"],
                customer_phone=serializer.validated_data.get("customer_phone", ""),
                billing_address=serializer.validated_data.get("billing_address") or {},
                shipping_address=serializer.validated_data.get("shipping_address") or {},
                notes=serializer.validated_data.get("notes", ""),
                shipping_rate_id=serializer.validated_data.get("shipping_rate_id"),
                discount_code=serializer.validated_data.get("discount_code", ""),
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        trigger_webhooks(
            order.site,
            "order.created",
            {
                "order_id": order.id,
                "order_number": order.order_number,
                "total": str(order.total),
                "customer_email": order.customer_email,
            },
        )
        _remember_checkout_order(request, order)
        return Response(OrderSerializer(order, context={"request": request}).data, status=status.HTTP_201_CREATED)


class SiteBlogFeed(Feed):
    def get_object(self, request, site_slug):
        ensure_seed_data()
        return get_object_or_404(Site, slug=site_slug)

    def title(self, obj: Site):
        return f"{obj.name} Blog"

    def link(self, obj: Site):
        return f"/preview/{obj.slug}/blog/"

    def description(self, obj: Site):
        return obj.tagline or obj.description or f"Published posts for {obj.name}"

    def items(self, obj: Site):
        return obj.posts.filter(status=Post.STATUS_PUBLISHED).order_by("-published_at")[:20]

    def item_title(self, item: Post):
        return item.title

    def item_description(self, item: Post):
        return item.excerpt or item.seo.get("meta_description") or item.title

    def item_link(self, item: Post):
        return preview_url_for_post(item)

    def item_pubdate(self, item: Post):
        return item.published_at or item.updated_at


def _resolve_site_locale(site: Site, locale_code: str | None):
    locales = list(site.locales.filter(is_enabled=True).order_by("-is_default", "code"))
    if not locales:
        return None

    default_locale = next((locale for locale in locales if locale.is_default), locales[0])
    if not locale_code:
        return default_locale

    try:
        matched_code = select_best_locale(locale_code, [locale.code for locale in locales])
    except ValueError as exc:
        raise Http404("Locale not found") from exc
    if not matched_code:
        raise Http404("Locale not found")

    matched_locale = next((locale for locale in locales if locale.code == matched_code), None)
    return matched_locale or default_locale


def _resolve_localized_page(site: Site, locale: SiteLocale | None, normalized_path: str):
    if locale and not locale.is_default:
        translation = (
            PageTranslation.objects.select_related("page", "locale")
            .filter(page__site=site, locale=locale, path=normalized_path)
            .first()
        )
        if translation:
            return translation.page, translation

    try:
        page = site.pages.get(path=normalized_path)
    except Page.DoesNotExist as exc:
        if normalized_path == "/":
            page = site.pages.filter(is_homepage=True).first()
            if not page:
                raise Http404("Homepage not found") from exc
        else:
            raise Http404("Page not found") from exc

    if locale and not locale.is_default:
        translation = page.translations.filter(locale=locale).select_related("locale").first()
        if translation:
            return page, translation
    return page, None


def public_page(request, site_slug: str, page_path: str = "", locale_code: str | None = None):
    ensure_seed_data()
    site = get_object_or_404(Site.objects.prefetch_related("locales", "pages__translations__locale"), slug=site_slug)

    normalized_path = "/" if not page_path else f'/{page_path.strip("/")}/'
    locale = _resolve_site_locale(site, locale_code)
    page, translation = _resolve_localized_page(site, locale, normalized_path)
    source_builder_data = translation.builder_data if translation else page.builder_data
    builder_meta = source_builder_data.get("metadata") if isinstance(source_builder_data, dict) else {}
    builder_seo = source_builder_data.get("seo") if isinstance(source_builder_data, dict) else {}
    render_cache = extract_render_cache(
        source_builder_data,
        html=translation.html if translation else page.html,
        css=translation.css if translation else page.css,
        js=translation.js if translation else page.js,
    )
    payload = {
        "title": (
            str(builder_meta.get("title") or "").strip()
            if isinstance(builder_meta, dict) and str(builder_meta.get("title") or "").strip()
            else (translation.title if translation else page.title)
        ),
        "seo": builder_seo if isinstance(builder_seo, dict) and builder_seo else (translation.seo if translation else page.seo),
        "page_settings": translation.page_settings if translation else page.page_settings,
        "builder_data": source_builder_data,
        "html": render_cache["html"],
        "css": render_cache["css"],
        "js": render_cache["js"],
    }
    experiment_context = evaluate_page_experiments(request, page, translation.locale if translation else locale)
    payload = apply_variant_to_page_payload(payload, experiment_context["assignments"])
    page_settings = payload["page_settings"] if isinstance(payload.get("page_settings"), dict) else {}
    seo_payload = payload["seo"] if isinstance(payload.get("seo"), dict) else {}

    if page_settings.get("document_mode") == "full_html" and str(payload["html"]).lstrip().lower().startswith("<!doctype html"):
        response = HttpResponse(payload["html"], content_type="text/html; charset=utf-8")
        return persist_experiment_cookies(
            response,
            experiment_context["visitor_id"],
            experiment_context["assignment_cookie"],
            visitor_cookie_changed=experiment_context["visitor_cookie_changed"],
            assignment_cookie_changed=experiment_context["assignment_cookie_changed"],
        )

    meta_title = seo_payload.get("meta_title") or f"{site.name} | {payload['title']}"
    meta_description = seo_payload.get("meta_description") or site.tagline or site.description or payload["title"]
    response = render(
        request,
        "builder/published_page.html",
        {
            "page_title": meta_title,
            "page_description": meta_description,
            "page_html": payload["html"],
            "page_css": payload["css"],
            "page_js": payload["js"],
            "theme_css": build_theme_css(site.theme),
            "base_css": BASE_BLOCK_CSS,
            "locale_code": locale.code.lower() if locale else "",
            "available_locales": [item.code.lower() for item in site.locales.filter(is_enabled=True)],
        },
    )
    return persist_experiment_cookies(
        response,
        experiment_context["visitor_id"],
        experiment_context["assignment_cookie"],
        visitor_cookie_changed=experiment_context["visitor_cookie_changed"],
        assignment_cookie_changed=experiment_context["assignment_cookie_changed"],
    )


def public_blog_index(request, site_slug: str):
    ensure_seed_data()
    site = get_object_or_404(Site, slug=site_slug)
    posts = site.posts.filter(status=Post.STATUS_PUBLISHED).prefetch_related("categories", "tags").order_by("-published_at")
    return render(
        request,
        "builder/post_index.html",
        {
            "site": site,
            "posts": posts,
            "theme_css": build_theme_css(site.theme),
            "base_css": BASE_BLOCK_CSS,
            "page_title": f"{site.name} | Blog",
            "page_description": site.tagline or site.description or f"Blog posts for {site.name}",
        },
    )


def public_blog_post(request, site_slug: str, post_slug: str):
    ensure_seed_data()
    site = get_object_or_404(Site, slug=site_slug)
    post = get_object_or_404(
        site.posts.prefetch_related("categories", "tags", "comments"),
        slug=post_slug,
        status=Post.STATUS_PUBLISHED,
    )

    meta_title = post.seo.get("meta_title") or f"{site.name} | {post.title}"
    meta_description = post.seo.get("meta_description") or post.excerpt or site.tagline or site.description or post.title
    return render(
        request,
        "builder/post_detail.html",
        {
            "site": site,
            "post": post,
            "theme_css": build_theme_css(site.theme),
            "base_css": BASE_BLOCK_CSS,
            "page_title": meta_title,
            "page_description": meta_description,
        },
    )


def public_shop_index(request, site_slug: str):
    ensure_seed_data()
    site = get_object_or_404(Site, slug=site_slug)
    search = (request.GET.get("q") or "").strip()
    category_slug = (request.GET.get("category") or "").strip()
    sort = (request.GET.get("sort") or "newest").strip()
    products = _shop_catalog_queryset(site, search=search, category_slug=category_slug, sort=sort)
    catalog_items = []
    for product in products:
        default_variant = product.variants.filter(is_active=True).order_by("-is_default", "title").first()
        catalog_items.append({"product": product, "default_variant": default_variant})
    categories = (
        site.product_categories.filter(products__status=Product.STATUS_PUBLISHED)
        .distinct()
        .order_by("name")
    )
    cart = get_or_create_cart(site, request.session)

    return render(
        request,
        "builder/shop_index.html",
        {
            "site": site,
            "catalog_items": catalog_items,
            "categories": categories,
            "search_query": search,
            "active_category": category_slug,
            "active_sort": sort,
            "cart_item_count": sum(item.quantity for item in cart.items.all()),
            "theme_css": build_theme_css(site.theme),
            "base_css": BASE_BLOCK_CSS,
            "page_title": f"{site.name} | Shop",
            "page_description": site.tagline or site.description or f"Shop products for {site.name}",
        },
    )


def public_shop_product(request, site_slug: str, product_slug: str):
    ensure_seed_data()
    site = get_object_or_404(Site, slug=site_slug)
    product = get_object_or_404(
        site.products.select_related("featured_media").prefetch_related("categories", "variants"),
        slug=product_slug,
        status=Product.STATUS_PUBLISHED,
    )
    if request.method == "POST":
        cart = get_or_create_cart(site, request.session)
        try:
            variant = resolve_variant(product, request.POST.get("variant_id"))
            quantity = max(1, int(request.POST.get("quantity") or 1))
            cart_item, created = CartItem.objects.get_or_create(
                cart=cart,
                product_variant=variant,
                defaults={"quantity": quantity},
            )
            if not created:
                cart_item.quantity += quantity
            ensure_variant_inventory(variant, cart_item.quantity)
            sync_cart_item(cart_item)
            cart_item.save()
            recalculate_cart(cart)
            return HttpResponseRedirect(f"/preview/{site.slug}/shop/cart/?notice=added")
        except (TypeError, ValueError, ProductVariant.DoesNotExist) as exc:
            error_message = str(exc) or "Unable to add this product to cart."
    else:
        error_message = ""

    variants = product.variants.filter(is_active=True).order_by("-is_default", "title")
    default_variant = variants.first()
    related_products = (
        site.products.filter(status=Product.STATUS_PUBLISHED, categories__in=product.categories.all())
        .exclude(pk=product.pk)
        .select_related("featured_media")
        .prefetch_related("variants")
        .distinct()[:3]
    )
    cart = get_or_create_cart(site, request.session)
    meta_title = product.seo.get("meta_title") or f"{site.name} | {product.title}"
    meta_description = product.seo.get("meta_description") or product.excerpt or site.tagline or site.description or product.title
    return render(
        request,
        "builder/shop_detail.html",
        {
            "site": site,
            "product": product,
            "variants": variants,
            "default_variant": default_variant,
            "related_products": related_products,
            "cart_item_count": sum(item.quantity for item in cart.items.all()),
            "notice": request.GET.get("notice", ""),
            "error_message": error_message,
            "theme_css": build_theme_css(site.theme),
            "base_css": BASE_BLOCK_CSS,
            "page_title": meta_title,
            "page_description": meta_description,
        },
    )


def public_shop_cart(request, site_slug: str):
    ensure_seed_data()
    site = get_object_or_404(Site, slug=site_slug)
    cart = get_or_create_cart(site, request.session)
    notice = request.GET.get("notice", "")
    error_message = ""
    completed_order = None

    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()
        if action == "update_item":
            cart_item = get_object_or_404(cart.items.select_related("product_variant"), pk=request.POST.get("item_id"))
            try:
                quantity = max(0, int(request.POST.get("quantity") or 1))
            except (TypeError, ValueError):
                quantity = 1
            if quantity == 0:
                cart_item.delete()
            else:
                ensure_variant_inventory(cart_item.product_variant, quantity)
                cart_item.quantity = quantity
                sync_cart_item(cart_item)
                cart_item.save()
            recalculate_cart(cart)
            return HttpResponseRedirect(f"/preview/{site.slug}/shop/cart/?notice=updated")

        if action == "remove_item":
            cart_item = get_object_or_404(cart.items.all(), pk=request.POST.get("item_id"))
            cart_item.delete()
            recalculate_cart(cart)
            return HttpResponseRedirect(f"/preview/{site.slug}/shop/cart/?notice=removed")

        pricing_payload = _shop_pricing_payload(request, site.slug)
        try:
            pricing = calculate_cart_pricing(
                cart,
                shipping_address=pricing_payload["shipping_address"],
                shipping_rate_id=pricing_payload["shipping_rate_id"],
                discount_code=pricing_payload["discount_code"],
            )
        except ValueError as exc:
            pricing = None
            error_message = str(exc)

        if action == "checkout" and pricing is not None:
            try:
                customer_name = str(request.POST.get("customer_name") or "").strip()
                customer_email = str(request.POST.get("customer_email") or "").strip()
                if not customer_name or not customer_email:
                    raise ValueError("Customer name and email are required.")
                completed_order = create_order_from_cart(
                    cart,
                    customer_name=customer_name,
                    customer_email=customer_email,
                    customer_phone=str(request.POST.get("customer_phone") or "").strip(),
                    billing_address={
                        "country": pricing_payload["shipping_address"].get("country", ""),
                        "state": pricing_payload["shipping_address"].get("state", ""),
                        "city": str(request.POST.get("billing_city") or "").strip(),
                    },
                    shipping_address={
                        "country": pricing_payload["shipping_address"].get("country", ""),
                        "state": pricing_payload["shipping_address"].get("state", ""),
                        "city": str(request.POST.get("shipping_city") or "").strip(),
                    },
                    notes=str(request.POST.get("notes") or "").strip(),
                    shipping_rate_id=pricing_payload["shipping_rate_id"],
                    discount_code=pricing_payload["discount_code"],
                )
                trigger_webhooks(
                    completed_order.site,
                    "order.created",
                    {
                        "order_id": completed_order.id,
                        "order_number": completed_order.order_number,
                        "total": str(completed_order.total),
                        "customer_email": completed_order.customer_email,
                    },
                )
                cart = get_or_create_cart(site, request.session)
                notice = "ordered"
            except ValueError as exc:
                error_message = str(exc)
    pricing_payload = _shop_pricing_payload(request, site.slug)
    try:
        pricing = calculate_cart_pricing(
            cart,
            shipping_address=pricing_payload["shipping_address"],
            shipping_rate_id=pricing_payload["shipping_rate_id"],
            discount_code=pricing_payload["discount_code"],
        )
    except ValueError as exc:
        pricing = {
            "subtotal": str(cart.subtotal),
            "shipping_total": "0.00",
            "shipping_original_total": "0.00",
            "tax_total": "0.00",
            "discount_total": "0.00",
            "total": str(cart.total),
            "shipping_zone": None,
            "available_shipping_rates": [],
            "shipping_rate": None,
            "discount": None,
            "tax_rate": None,
            "pricing_details": pricing_payload["checkout_state"],
        }
        error_message = str(exc)

    pricing.pop("discount_code_obj", None)
    return render(
        request,
        "builder/shop_cart.html",
        {
            "site": site,
            "cart": cart,
            "cart_items": list(cart.items.select_related("product_variant", "product_variant__product")),
            "pricing": pricing,
            "checkout_state": pricing_payload["checkout_state"],
            "completed_order": completed_order,
            "notice": notice,
            "error_message": error_message,
            "theme_css": build_theme_css(site.theme),
            "base_css": BASE_BLOCK_CSS,
            "page_title": f"{site.name} | Cart",
            "page_description": f"Review your cart and checkout for {site.name}",
        },
    )


def public_sitemap(request, site_slug: str):
    ensure_seed_data()
    site = get_object_or_404(Site.objects.prefetch_related("locales", "pages__translations__locale"), slug=site_slug)
    page_entries = [
        {
            "loc": request.build_absolute_uri(f"/preview/{site.slug}/" if page.is_homepage else f"/preview/{site.slug}{page.path}"),
            "lastmod": page.updated_at,
        }
        for page in site.pages.filter(status=Page.STATUS_PUBLISHED).order_by("-updated_at")
    ]
    translation_entries = [
        {
            "loc": request.build_absolute_uri(preview_url_for_page_translation(translation)),
            "lastmod": translation.updated_at,
        }
        for translation in PageTranslation.objects.select_related("page", "locale", "page__site")
        .filter(page__site=site, status=PageTranslation.STATUS_PUBLISHED, locale__is_enabled=True)
        .order_by("-updated_at")
    ]
    post_entries = [
        {
            "loc": request.build_absolute_uri(preview_url_for_post(post)),
            "lastmod": post.updated_at,
        }
        for post in site.posts.filter(status=Post.STATUS_PUBLISHED).order_by("-updated_at")
    ]
    product_entries = [
        {
            "loc": request.build_absolute_uri(preview_url_for_product(product)),
            "lastmod": product.updated_at,
        }
        for product in site.products.filter(status=Product.STATUS_PUBLISHED).order_by("-updated_at")
    ]
    response = render(
        request,
        "builder/sitemap.xml",
        {
            "entries": [*page_entries, *translation_entries, *post_entries, *product_entries],
        },
        content_type="application/xml",
    )
    return response


class BlockTemplateViewSet(viewsets.ModelViewSet):
    serializer_class = BlockTemplateSerializer

    def get_queryset(self):
        ensure_seed_data()
        queryset = BlockTemplate.objects.select_related("site").order_by("-is_global", "-usage_count", "name")
        user = self.request.user
        if not user.is_authenticated:
            return queryset.none()
        if not user.is_superuser:
            from .workspace_views import filter_sites_by_permission

            allowed_sites = filter_sites_by_permission(user, Site.objects.all())
            queryset = queryset.filter(models.Q(is_global=True) | models.Q(site__in=allowed_sites))

        site_id = self.request.query_params.get("site")
        category = self.request.query_params.get("category")
        is_global = self.request.query_params.get("global")
        template_status = self.request.query_params.get("status")
        search = self.request.query_params.get("search")
        marketplace = self.request.query_params.get("marketplace")

        if site_id:
            queryset = queryset.filter(models.Q(site_id=site_id) | models.Q(is_global=True))
        if category:
            queryset = queryset.filter(category=category)
        if is_global in {"1", "true", "yes"}:
            queryset = queryset.filter(is_global=True)
        if template_status:
            queryset = queryset.filter(status=template_status)
        if marketplace in {"1", "true", "yes"}:
            from .models import BlockTemplate as BT
            queryset = queryset.filter(status=BT.STATUS_MARKETPLACE)
        if search:
            queryset = queryset.filter(
                models.Q(name__icontains=search) | models.Q(description__icontains=search)
            )
        return queryset

    def _check_template_edit_permission(self, template: BlockTemplate):
        if template.is_global:
            if not self.request.user.is_superuser:
                raise PermissionDenied("Only platform administrators can modify global templates.")
            return

        site = template.site
        if site is None:
            raise PermissionDenied("Template is not associated with a site.")

        from .workspace_views import check_site_permission

        if not check_site_permission(self.request.user, site, require_edit=True):
            raise PermissionDenied("You don't have permission to edit templates for this site.")

    def _validate_create_update_permissions(self, *, site, is_global: bool):
        if is_global:
            if not self.request.user.is_superuser:
                raise PermissionDenied("Only platform administrators can create or update global templates.")
            return
        if site is None:
            raise ValidationError({"site": "Site is required for non-global templates."})
        from .workspace_views import check_site_permission

        if not check_site_permission(self.request.user, site, require_edit=True):
            raise PermissionDenied("You don't have permission to manage templates for this site.")

    def perform_create(self, serializer):
        site = serializer.validated_data.get("site")
        is_global = bool(serializer.validated_data.get("is_global", False))
        self._validate_create_update_permissions(site=site, is_global=is_global)
        serializer.save()

    def perform_update(self, serializer):
        template = serializer.instance
        if template.is_global and not self.request.user.is_superuser:
            raise PermissionDenied("Only platform administrators can modify global templates.")
        site = serializer.validated_data.get("site", template.site)
        is_global = bool(serializer.validated_data.get("is_global", template.is_global))
        self._validate_create_update_permissions(site=site, is_global=is_global)
        serializer.save()

    def perform_destroy(self, instance):
        self._check_template_edit_permission(instance)
        instance.delete()

    @action(detail=True, methods=["post"])
    def use(self, request, pk=None):
        template = self.get_object()
        template.usage_count += 1
        template.save(update_fields=["usage_count", "updated_at"])
        return Response(BlockTemplateSerializer(template, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def publish(self, request, pk=None):
        from .models import BlockTemplate as BT
        template = self.get_object()
        self._check_template_edit_permission(template)
        template.status = BT.STATUS_PUBLISHED
        template.save(update_fields=["status", "updated_at"])
        return Response(BlockTemplateSerializer(template, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def unpublish(self, request, pk=None):
        from .models import BlockTemplate as BT
        template = self.get_object()
        self._check_template_edit_permission(template)
        template.status = BT.STATUS_DRAFT
        template.save(update_fields=["status", "updated_at"])
        return Response(BlockTemplateSerializer(template, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def submit_to_marketplace(self, request, pk=None):
        from .models import BlockTemplate as BT
        template = self.get_object()
        self._check_template_edit_permission(template)
        template.status = BT.STATUS_MARKETPLACE
        template.is_global = True
        template.save(update_fields=["status", "is_global", "updated_at"])
        return Response(BlockTemplateSerializer(template, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def disable(self, request, pk=None):
        from .models import BlockTemplate as BT
        template = self.get_object()
        self._check_template_edit_permission(template)
        template.status = BT.STATUS_DISABLED
        template.save(update_fields=["status", "updated_at"])
        return Response(BlockTemplateSerializer(template, context={"request": request}).data)


class ReusableSectionViewSet(SitePermissionMixin, viewsets.ModelViewSet):
    serializer_class = ReusableSectionSerializer

    def get_queryset(self):
        queryset = ReusableSection.objects.select_related("site").order_by("name")
        site_id = self.request.query_params.get("site")
        section_status = self.request.query_params.get("status")
        if site_id:
            queryset = queryset.filter(site_id=site_id)
        if section_status:
            queryset = queryset.filter(status=section_status)
        return self.filter_by_site_permission(queryset)

    @action(detail=True, methods=["post"])
    def publish(self, request, pk=None):
        section = self.get_object()
        section.status = ReusableSection.STATUS_PUBLISHED
        section.published_at = timezone.now()
        section.save(update_fields=["status", "published_at", "updated_at"])
        trigger_webhooks(
            section.site,
            "section.published",
            {"section_id": section.id, "slug": section.slug, "name": section.name},
        )
        return Response(self.get_serializer(section).data)

    @action(detail=True, methods=["post"])
    def unpublish(self, request, pk=None):
        section = self.get_object()
        section.status = ReusableSection.STATUS_DRAFT
        section.save(update_fields=["status", "updated_at"])
        trigger_webhooks(
            section.site,
            "section.unpublished",
            {"section_id": section.id, "slug": section.slug, "name": section.name},
        )
        return Response(self.get_serializer(section).data)

    @action(detail=True, methods=["post"])
    def archive(self, request, pk=None):
        section = self.get_object()
        section.status = ReusableSection.STATUS_ARCHIVED
        section.save(update_fields=["status", "updated_at"])
        return Response(self.get_serializer(section).data)

    @action(detail=True, methods=["post"])
    def validate_layout(self, request, pk=None):
        section = self.get_object()
        schema = section.schema if isinstance(section.schema, dict) else {}
        layout = schema.get("layout")
        if not isinstance(layout, dict):
            return Response({"valid": False, "errors": ["schema.layout must be an object."]}, status=status.HTTP_400_BAD_REQUEST)
        if not isinstance(layout.get("type"), str) or not layout.get("type"):
            return Response({"valid": False, "errors": ["schema.layout.type is required."]}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"valid": True})


class ThemeTemplateViewSet(SitePermissionMixin, viewsets.ModelViewSet):
    serializer_class = ThemeTemplateSerializer

    def get_queryset(self):
        queryset = ThemeTemplate.objects.select_related("site").order_by("-is_global", "name")
        site_id = self.request.query_params.get("site")
        global_only = self.request.query_params.get("global")
        if site_id:
            queryset = queryset.filter(site_id=site_id)
        if global_only in {"1", "true", "yes"}:
            queryset = queryset.filter(is_global=True)
        scoped_queryset = self.filter_by_site_permission(queryset.filter(is_global=False))
        if self.request.user.is_superuser:
            return queryset
        return (scoped_queryset | queryset.filter(is_global=True)).distinct()

    def _check_template_permission(self, template: ThemeTemplate):
        if template.is_global and not self.request.user.is_superuser:
            raise PermissionDenied("Only super admins can edit global themes.")
        if template.site_id:
            self.check_site_edit_permission(template.site)

    def perform_create(self, serializer):
        is_global = bool(serializer.validated_data.get("is_global", False))
        site = serializer.validated_data.get("site")
        if is_global and not self.request.user.is_superuser:
            raise PermissionDenied("Only super admins can create global themes.")
        if not is_global and site is None:
            raise ValidationError({"site": "Site is required for non-global themes."})
        if site:
            self.check_site_edit_permission(site)
        serializer.save()

    def perform_update(self, serializer):
        self._check_template_permission(serializer.instance)
        super().perform_update(serializer)

    def perform_destroy(self, instance):
        self._check_template_permission(instance)
        super().perform_destroy(instance)

    @action(detail=True, methods=["post"])
    def publish(self, request, pk=None):
        template = self.get_object()
        self._check_template_permission(template)
        template.status = ThemeTemplate.STATUS_PUBLISHED
        template.save(update_fields=["status", "updated_at"])
        return Response(self.get_serializer(template).data)


class SiteShellViewSet(SitePermissionMixin, viewsets.ModelViewSet):
    serializer_class = SiteShellSerializer

    def get_queryset(self):
        queryset = SiteShell.objects.select_related("site", "header_menu", "footer_menu").order_by("site__name")
        site_id = self.request.query_params.get("site")
        if site_id:
            queryset = queryset.filter(site_id=site_id)
        return self.filter_by_site_permission(queryset)

    def create(self, request, *args, **kwargs):
        site = self.get_site_from_request(key="site", source="data", require_edit=True)
        shell, _ = SiteShell.objects.get_or_create(site=site)
        serializer = self.get_serializer(shell, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class PublishSnapshotViewSet(SitePermissionMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = PublishSnapshotSerializer

    def get_queryset(self):
        queryset = PublishSnapshot.objects.select_related("site", "actor").order_by("-created_at")
        site_id = self.request.query_params.get("site")
        target_type = self.request.query_params.get("target_type")
        target_id = self.request.query_params.get("target_id")
        if site_id:
            queryset = queryset.filter(site_id=site_id)
        if target_type:
            queryset = queryset.filter(target_type=target_type)
        if target_id:
            queryset = queryset.filter(target_id=target_id)
        return self.filter_by_site_permission(queryset)

    @action(detail=True, methods=["post"])
    def restore(self, request, pk=None):
        snapshot = self.get_object()
        self.check_site_edit_permission(snapshot.site)
        payload = snapshot.snapshot if isinstance(snapshot.snapshot, dict) else {}

        if snapshot.target_type == PublishSnapshot.TARGET_PAGE:
            page = get_object_or_404(Page.objects.select_related("site"), pk=snapshot.target_id, site=snapshot.site)
            for field in ("title", "slug", "path", "seo", "page_settings", "builder_data", "html", "css", "js"):
                if field in payload:
                    setattr(page, field, payload.get(field))
            page.status = Page.STATUS_DRAFT
            page.save()
            create_revision(page, f"Restored from snapshot {snapshot.id}")
            trigger_webhooks(page.site, "page.restored", {"page_id": page.id, "snapshot_id": snapshot.id})
            return Response(PageSerializer(page, context={"request": request}).data)

        if snapshot.target_type == PublishSnapshot.TARGET_POST:
            post = get_object_or_404(Post.objects.select_related("site"), pk=snapshot.target_id, site=snapshot.site)
            for field in ("title", "slug", "excerpt", "body_html", "seo"):
                if field in payload:
                    setattr(post, field, payload.get(field))
            post.status = Post.STATUS_DRAFT
            post.save(update_fields=["title", "slug", "excerpt", "body_html", "seo", "status", "updated_at"])
            trigger_webhooks(post.site, "post.restored", {"post_id": post.id, "snapshot_id": snapshot.id})
            return Response(PostSerializer(post, context={"request": request}).data)

        if snapshot.target_type == PublishSnapshot.TARGET_PRODUCT:
            product = get_object_or_404(Product.objects.select_related("site"), pk=snapshot.target_id, site=snapshot.site)
            for field in ("title", "slug", "excerpt", "description_html", "seo", "settings"):
                if field in payload:
                    setattr(product, field, payload.get(field))
            product.status = Product.STATUS_DRAFT
            product.save(update_fields=["title", "slug", "excerpt", "description_html", "seo", "settings", "status", "updated_at"])
            trigger_webhooks(product.site, "product.restored", {"product_id": product.id, "snapshot_id": snapshot.id})
            return Response(ProductSerializer(product, context={"request": request}).data)

        return Response({"detail": "Unsupported snapshot target."}, status=status.HTTP_400_BAD_REQUEST)


class PreviewTokenViewSet(SitePermissionMixin, viewsets.ModelViewSet):
    serializer_class = PreviewTokenSerializer

    def get_queryset(self):
        queryset = PreviewToken.objects.select_related("site", "page", "locale", "created_by").order_by("-created_at")
        site_id = self.request.query_params.get("site")
        page_id = self.request.query_params.get("page")
        include_revoked = self.request.query_params.get("include_revoked")
        if site_id:
            queryset = queryset.filter(site_id=site_id)
        if page_id:
            queryset = queryset.filter(page_id=page_id)
        if include_revoked not in {"1", "true", "yes"}:
            queryset = queryset.filter(revoked_at__isnull=True)
        return self.filter_by_site_permission(queryset)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        site = serializer.validated_data["site"]
        self.check_site_edit_permission(site)
        expires_at = serializer.validated_data.get("expires_at")
        if expires_at is None:
            expires_at = timezone.now() + timedelta(hours=2)
        raw_token = secrets.token_urlsafe(48)
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        preview_token = serializer.save(
            token_hash=token_hash,
            expires_at=expires_at,
            created_by=request.user if request.user.is_authenticated else None,
        )
        data = self.get_serializer(preview_token).data
        data["token"] = raw_token
        return Response(data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def revoke(self, request, pk=None):
        token = self.get_object()
        if token.revoked_at is None:
            token.revoked_at = timezone.now()
            token.save(update_fields=["revoked_at", "updated_at"])
        return Response(self.get_serializer(token).data)

    @action(
        detail=False,
        methods=["post"],
        permission_classes=[permissions.AllowAny],
        authentication_classes=[],
        url_path="resolve",
    )
    def resolve(self, request):
        raw_token = (request.data.get("token") or "").strip()
        if not raw_token:
            return Response({"detail": "token is required."}, status=status.HTTP_400_BAD_REQUEST)
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        token = (
            PreviewToken.objects.select_related("site", "page", "locale")
            .filter(
                token_hash=token_hash,
                revoked_at__isnull=True,
                expires_at__gt=timezone.now(),
            )
            .first()
        )
        if token is None:
            return Response({"detail": "Preview token is invalid or expired."}, status=status.HTTP_404_NOT_FOUND)
        token.used_at = timezone.now()
        token.save(update_fields=["used_at", "updated_at"])

        page = token.page
        if page is None:
            return Response({"detail": "Preview token has no page target."}, status=status.HTTP_400_BAD_REQUEST)
        translation_payload = None
        if token.locale_id:
            translation = (
                page.translations.select_related("locale")
                .filter(locale_id=token.locale_id)
                .first()
            )
            if translation:
                translation_payload = {
                    "id": translation.id,
                    "locale": translation.locale.code,
                    "title": translation.title,
                    "path": translation.path,
                    "builder_schema_version": translation.builder_schema_version,
                    "builder_data": translation.builder_data,
                    "seo": translation.seo,
                    "page_settings": translation.page_settings,
                    "html": translation.html,
                    "css": translation.css,
                    "js": translation.js,
                    "status": translation.status,
                }
        return Response(
            {
                "site": {"id": page.site_id, "slug": page.site.slug},
                "page": PageSerializer(page, context={"request": request}).data,
                "translation": translation_payload,
                "preview": {"expires_at": token.expires_at, "used_at": token.used_at},
            }
        )


class URLRedirectViewSet(SitePermissionMixin, viewsets.ModelViewSet):
    serializer_class = URLRedirectSerializer

    def get_queryset(self):
        ensure_seed_data()
        queryset = URLRedirect.objects.select_related("site").order_by("site", "source_path")
        site_id = self.request.query_params.get("site")
        redirect_status = self.request.query_params.get("status")
        if site_id:
            queryset = queryset.filter(site_id=site_id)
        if redirect_status:
            queryset = queryset.filter(status=redirect_status)
        return self.filter_by_site_permission(queryset)

    @action(detail=True, methods=["post"])
    def toggle_status(self, request, pk=None):
        redirect = self.get_object()
        redirect.status = (
            URLRedirect.STATUS_INACTIVE
            if redirect.status == URLRedirect.STATUS_ACTIVE
            else URLRedirect.STATUS_ACTIVE
        )
        redirect.save(update_fields=["status", "updated_at"])
        return Response(URLRedirectSerializer(redirect, context={"request": request}).data)


class RobotsTxtViewSet(SitePermissionMixin, viewsets.ViewSet):
    """Per-site robots.txt management."""

    def _get_site(self, pk, *, require_edit: bool):
        site = get_object_or_404(Site.objects.select_related("workspace"), pk=pk)
        if require_edit:
            self.check_site_edit_permission(site)
        else:
            from .workspace_views import check_site_permission

            if not check_site_permission(self.request.user, site, require_edit=False):
                raise PermissionDenied("You don't have permission to access this site.")
        return site

    def retrieve(self, request, pk=None):
        from .models import RobotsTxt
        site = self._get_site(pk, require_edit=False)
        robots, _ = RobotsTxt.objects.get_or_create(
            site=site,
            defaults={"content": "User-agent: *\nAllow: /", "is_custom": False},
        )
        return Response({
            "site": site.id,
            "content": robots.content,
            "is_custom": robots.is_custom,
            "updated_at": robots.updated_at,
        })

    def _save_robots(self, request, pk):
        from .models import RobotsTxt
        site = self._get_site(pk, require_edit=True)
        robots, _ = RobotsTxt.objects.get_or_create(
            site=site,
            defaults={"content": "User-agent: *\nAllow: /", "is_custom": False},
        )
        content = request.data.get("content")
        is_custom = request.data.get("is_custom")
        if content is not None:
            robots.content = content
            robots.is_custom = True
        if is_custom is not None:
            robots.is_custom = bool(is_custom)
        robots.save()
        return Response({
            "site": site.id,
            "content": robots.content,
            "is_custom": robots.is_custom,
            "updated_at": robots.updated_at,
        })

    def update(self, request, pk=None):
        return self._save_robots(request, pk)

    def partial_update(self, request, pk=None):
        return self._save_robots(request, pk)

    @action(detail=True, methods=["post"])
    def reset(self, request, pk=None):
        from .models import RobotsTxt
        site = self._get_site(pk, require_edit=True)
        robots, _ = RobotsTxt.objects.get_or_create(site=site, defaults={})
        robots.content = "User-agent: *\nAllow: /"
        robots.is_custom = False
        robots.save()
        return Response({
            "site": site.id,
            "content": robots.content,
            "is_custom": robots.is_custom,
            "updated_at": robots.updated_at,
        })


class DomainContactViewSet(SitePermissionMixin, viewsets.ModelViewSet):
    serializer_class = DomainContactSerializer

    def get_queryset(self):
        queryset = DomainContact.objects.select_related("site").order_by("role", "last_name")
        site_id = self.request.query_params.get("site")
        if site_id:
            queryset = queryset.filter(site_id=site_id)
        return self.filter_by_site_permission(queryset)


class DomainViewSet(SitePermissionMixin, viewsets.ModelViewSet):
    serializer_class = DomainSerializer

    def get_queryset(self):
        queryset = Domain.objects.select_related("site", "registrant_contact").order_by("-is_primary", "domain_name")
        site_id = self.request.query_params.get("site")
        registration_status = self.request.query_params.get("registration_status")
        expiry_warning = self.request.query_params.get("expiry_warning")
        if site_id:
            queryset = queryset.filter(site_id=site_id)
        if registration_status:
            queryset = queryset.filter(registration_status=registration_status)
        if expiry_warning in {"1", "true", "yes"}:
            from django.utils import timezone as tz
            import datetime
            threshold = tz.now() + datetime.timedelta(days=90)
            queryset = queryset.filter(expires_at__lte=threshold, expires_at__isnull=False)
        return self.filter_by_site_permission(queryset)

    @action(detail=False, methods=["post"])
    def check_availability(self, request):
        """Check domain availability via WHOIS or Namecheap API."""
        domains_raw = request.data.get("domains", [])
        if isinstance(domains_raw, str):
            domains_raw = [d.strip() for d in domains_raw.split(",") if d.strip()]
        if not domains_raw:
            return Response({"detail": "Provide 'domains' as a list or comma-separated string."}, status=status.HTTP_400_BAD_REQUEST)
        if len(domains_raw) > 50:
            return Response({"detail": "Maximum 50 domains per request."}, status=status.HTTP_400_BAD_REQUEST)

        from .domain_services import check_availability, get_namecheap_client_from_settings
        client = get_namecheap_client_from_settings()
        results = []
        if client and len(domains_raw) > 1:
            try:
                api_results = client.check_availability(domains_raw)
                for r in api_results:
                    avail = DomainAvailability.objects.create(
                        domain_name=r["domain"],
                        available=r["available"],
                        registrar="namecheap",
                        raw_response=r,
                    )
                    results.append(DomainAvailabilitySerializer(avail).data)
                return Response(results)
            except Exception:
                pass

        for domain_name in domains_raw:
            result = check_availability(domain_name)
            avail = DomainAvailability.objects.create(
                domain_name=domain_name,
                available=result["available"],
                registrar=result.get("source", ""),
                raw_response={k: v for k, v in result.items() if k != "whois_data"},
            )
            results.append(DomainAvailabilitySerializer(avail).data)
        return Response(results)

    @action(detail=False, methods=["post"])
    def register(self, request):
        """Register a domain via Namecheap API."""
        from .domain_services import get_namecheap_client_from_settings
        client = get_namecheap_client_from_settings()
        if not client:
            return Response(
                {"detail": "Registrar not configured. Set NAMECHEAP_API_USER, NAMECHEAP_API_KEY, NAMECHEAP_USERNAME, NAMECHEAP_CLIENT_IP in environment."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        domain_name = request.data.get("domain_name", "").strip().lower()
        years = int(request.data.get("years", 1))
        site_id = request.data.get("site")
        contact_id = request.data.get("contact_id")
        privacy = bool(request.data.get("privacy_enabled", False))
        auto_renew = bool(request.data.get("auto_renew", True))

        if not domain_name:
            return Response({"detail": "domain_name is required."}, status=status.HTTP_400_BAD_REQUEST)
        if not site_id:
            return Response({"detail": "site is required."}, status=status.HTTP_400_BAD_REQUEST)
        if not contact_id:
            return Response({"detail": "contact_id is required."}, status=status.HTTP_400_BAD_REQUEST)

        site = self.get_site_from_request(key="site", source="data", require_edit=True)
        contact_obj = get_object_or_404(DomainContact, pk=contact_id, site=site)

        contact = {
            "first_name": contact_obj.first_name,
            "last_name": contact_obj.last_name,
            "email": contact_obj.email,
            "phone": contact_obj.phone,
            "organization": contact_obj.organization,
            "address1": contact_obj.address1,
            "city": contact_obj.city,
            "state": contact_obj.state,
            "postal_code": contact_obj.postal_code,
            "country": contact_obj.country,
        }

        try:
            result = client.register_domain(domain_name, years, contact, privacy=privacy)
        except Exception as exc:
            return Response({"detail": f"Registrar error: {exc}"}, status=status.HTTP_502_BAD_GATEWAY)

        if result.get("success"):
            import datetime
            from django.utils import timezone as tz
            domain_obj, _ = Domain.objects.get_or_create(
                domain_name=domain_name,
                defaults={"site": site},
            )
            domain_obj.site = site
            domain_obj.registration_status = Domain.REG_STATUS_ACTIVE
            domain_obj.registrar = "namecheap"
            domain_obj.registered_at = tz.now()
            domain_obj.expires_at = tz.now() + datetime.timedelta(days=365 * years)
            domain_obj.privacy_enabled = privacy
            domain_obj.auto_renew = auto_renew
            domain_obj.registrant_contact = contact_obj
            domain_obj.status = Domain.STATUS_VERIFIED
            domain_obj.verified_at = tz.now()
            domain_obj.save()
            return Response(DomainSerializer(domain_obj, context={"request": request}).data, status=status.HTTP_201_CREATED)
        else:
            errors = result.get("errors", ["Unknown registrar error."])
            return Response({"detail": "; ".join(errors), "raw": result.get("raw_xml", "")[:500]}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"])
    def verify(self, request, pk=None):
        """Generate verification token and perform real DNS TXT check."""
        from uuid import uuid4
        from django.utils import timezone as tz
        from .domain_services import verify_domain_ownership, build_verification_instructions

        domain = self.get_object()
        if not domain.verification_token:
            domain.verification_token = uuid4().hex
            domain.save(update_fields=["verification_token", "updated_at"])

        force_check = request.data.get("check", False)
        if force_check or request.data.get("check_now", False):
            domain.last_verification_attempt = tz.now()
            success, message = verify_domain_ownership(domain.domain_name, domain.verification_token)
            if success:
                domain.status = Domain.STATUS_VERIFIED
                domain.verified_at = tz.now()
                domain.verification_error = ""
            else:
                domain.status = Domain.STATUS_FAILED
                domain.verification_error = message
            domain.save(update_fields=["status", "verified_at", "last_verification_attempt", "verification_error", "updated_at"])

        instructions = build_verification_instructions(domain.domain_name, domain.verification_token)
        data = DomainSerializer(domain, context={"request": request}).data
        data["verification_instructions"] = instructions
        return Response(data)

    @action(detail=True, methods=["post"])
    def set_primary(self, request, pk=None):
        domain = self.get_object()
        Domain.objects.filter(site=domain.site, is_primary=True).exclude(pk=domain.pk).update(is_primary=False)
        domain.is_primary = True
        domain.save(update_fields=["is_primary", "updated_at"])
        return Response(DomainSerializer(domain, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def refresh_whois(self, request, pk=None):
        """Fetch fresh WHOIS data and cache it on the domain record."""
        from django.utils import timezone as tz
        from .domain_services import whois_query
        domain = self.get_object()
        data = whois_query(domain.domain_name)
        domain.whois_data = {k: v for k, v in data.items() if k != "raw"}
        domain.whois_fetched_at = tz.now()
        if data.get("expiry_date") and not domain.expires_at:
            from django.utils.dateparse import parse_datetime
            parsed = parse_datetime(str(data["expiry_date"]))
            if parsed:
                domain.expires_at = parsed
        if data.get("registrar") and not domain.registrar:
            domain.registrar = data["registrar"]
        if data.get("name_servers"):
            domain.nameservers = data["name_servers"]
        domain.save(update_fields=["whois_data", "whois_fetched_at", "expires_at", "registrar", "nameservers", "updated_at"])
        return Response(DomainSerializer(domain, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def import_from_registrar(self, request, pk=None):
        """Pull live info from Namecheap for a domain already in the account."""
        from .domain_services import get_namecheap_client_from_settings
        client = get_namecheap_client_from_settings()
        if not client:
            return Response({"detail": "Registrar not configured."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        domain = self.get_object()
        try:
            info = client.get_domain_info(domain.domain_name)
        except Exception as exc:
            return Response({"detail": f"Registrar error: {exc}"}, status=status.HTTP_502_BAD_GATEWAY)
        from django.utils.dateparse import parse_datetime
        from django.utils import timezone as tz
        if info.get("expires"):
            parsed = parse_datetime(info["expires"])
            if parsed:
                domain.expires_at = parsed
        if info.get("created"):
            parsed = parse_datetime(info["created"])
            if parsed:
                domain.registered_at = parsed
        domain.registrar = "namecheap"
        domain.registration_status = Domain.REG_STATUS_ACTIVE
        domain.auto_renew = info.get("auto_renew", "").lower() == "true"
        domain.transfer_lock = info.get("is_locked", "").lower() == "true"
        domain.save(update_fields=["expires_at", "registered_at", "registrar", "registration_status", "auto_renew", "transfer_lock", "updated_at"])
        return Response(DomainSerializer(domain, context={"request": request}).data)


class MediaFolderViewSet(SitePermissionMixin, viewsets.ModelViewSet):
    serializer_class = MediaFolderSerializer

    def get_queryset(self):
        ensure_seed_data()
        queryset = MediaFolder.objects.select_related("site", "parent").order_by("path", "name")
        site_id = self.request.query_params.get("site")
        if site_id:
            queryset = queryset.filter(site_id=site_id)
        return self.filter_by_site_permission(queryset)


class NavigationMenuViewSet(SitePermissionMixin, viewsets.ModelViewSet):
    serializer_class = NavigationMenuSerializer

    def get_queryset(self):
        ensure_seed_data()
        queryset = NavigationMenu.objects.select_related("site").order_by("location", "name")
        site_id = self.request.query_params.get("site")
        if site_id:
            queryset = queryset.filter(site_id=site_id)
        return self.filter_by_site_permission(queryset)


class WebhookViewSet(SitePermissionMixin, viewsets.ModelViewSet):
    serializer_class = WebhookSerializer

    def get_queryset(self):
        ensure_seed_data()
        queryset = Webhook.objects.select_related("site").order_by("event", "name")
        site_id = self.request.query_params.get("site")
        if site_id:
            queryset = queryset.filter(site_id=site_id)
        return self.filter_by_site_permission(queryset)

    @action(detail=True, methods=["post"])
    def test(self, request, pk=None):
        webhook = self.get_object()
        trigger_webhooks(
            webhook.site,
            webhook.event,
            {"test": True, "event": webhook.event, "webhook_id": webhook.id},
        )
        return Response({"detail": "Test dispatch enqueued."})


# ---------------------------------------------------------------------------
# SEO: analytics (existing, now upgraded with aggregate action)
# ---------------------------------------------------------------------------

class SEOAnalyticsViewSet(SitePermissionMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = SEOAnalyticsSerializer

    def get_queryset(self):
        ensure_seed_data()
        queryset = SEOAnalytics.objects.select_related("site", "page").order_by("-date")
        site_id = self.request.query_params.get("site")
        page_id = self.request.query_params.get("page_id") or self.request.query_params.get("page")
        if site_id:
            queryset = queryset.filter(site_id=site_id)
        if page_id:
            queryset = queryset.filter(page_id=page_id)
        return self.filter_by_site_permission(queryset)

    @action(detail=False, methods=["get"])
    def summary(self, request):
        """Return aggregated impressions/clicks/position over the last 90 days."""
        from django.db.models import Avg, Sum
        site = self.get_site_from_request(key="site", source="query", require_edit=False)
        qs = SEOAnalytics.objects.filter(site=site)
        agg = qs.aggregate(
            total_impressions=Sum("impressions"),
            total_clicks=Sum("clicks"),
            avg_position=Avg("average_position"),
            avg_ctr=Avg("ctr"),
        )
        return Response(agg)


# ---------------------------------------------------------------------------
# SEO: audit
# ---------------------------------------------------------------------------

class SEOAuditViewSet(SitePermissionMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = SEOAuditSerializer

    def get_queryset(self):
        ensure_seed_data()
        queryset = SEOAudit.objects.select_related("site", "page").order_by("-created_at")
        site_id = self.request.query_params.get("site")
        page_id = self.request.query_params.get("page_id") or self.request.query_params.get("page")
        if site_id:
            queryset = queryset.filter(site_id=site_id)
        if page_id:
            queryset = queryset.filter(page_id=page_id)
        return self.filter_by_site_permission(queryset)

    @action(detail=False, methods=["post"])
    def run(self, request):
        """
        Trigger an on-demand SEO audit for a page.
        Body: { "page": <id> }
        Runs synchronously (suitable for SQLite / no queue setup).
        """
        from .seo_services import run_page_audit

        page_id = request.data.get("page")
        if not page_id:
            return Response({"detail": "'page' field required."}, status=status.HTTP_400_BAD_REQUEST)

        page = get_object_or_404(self.filter_by_site_permission(Page.objects.select_related("site")), pk=page_id)
        self.check_site_edit_permission(page.site)
        base_url = request.build_absolute_uri("/").rstrip("/")
        audit = run_page_audit(page, base_url)
        return Response(SEOAuditSerializer(audit, context={"request": request}).data)


# ---------------------------------------------------------------------------
# SEO: tracked keywords + rank entries
# ---------------------------------------------------------------------------

class TrackedKeywordViewSet(SitePermissionMixin, viewsets.ModelViewSet):
    serializer_class = TrackedKeywordSerializer

    def get_queryset(self):
        ensure_seed_data()
        queryset = TrackedKeyword.objects.select_related("site").prefetch_related("rank_entries").order_by("keyword")
        site_id = self.request.query_params.get("site")
        if site_id:
            queryset = queryset.filter(site_id=site_id)
        return self.filter_by_site_permission(queryset)

    @action(detail=True, methods=["post"])
    def add_rank(self, request, pk=None):
        """Add a manual rank entry for a tracked keyword."""
        keyword = self.get_object()
        serializer = KeywordRankEntrySerializer(data={**request.data, "keyword": keyword.id})
        serializer.is_valid(raise_exception=True)
        entry = serializer.save(keyword=keyword, source="manual")
        return Response(KeywordRankEntrySerializer(entry).data, status=status.HTTP_201_CREATED)


class KeywordRankEntryViewSet(SitePermissionMixin, viewsets.ModelViewSet):
    serializer_class = KeywordRankEntrySerializer
    site_lookup_field = "keyword__site"

    def get_queryset(self):
        queryset = KeywordRankEntry.objects.select_related("keyword__site").order_by("-date")
        keyword_id = self.request.query_params.get("keyword")
        if keyword_id:
            queryset = queryset.filter(keyword_id=keyword_id)
        return self.filter_by_site_permission(queryset)


# ---------------------------------------------------------------------------
# SEO: settings
# ---------------------------------------------------------------------------

class SEOSettingsViewSet(SitePermissionMixin, viewsets.ViewSet):
    """Per-site SEO configuration (singleton per site)."""

    def retrieve(self, request, pk=None):
        ensure_seed_data()
        site = get_object_or_404(self.filter_by_site_permission(Site.objects.all()), pk=pk)
        settings_obj, _ = SEOSettings.objects.get_or_create(site=site)
        return Response(SEOSettingsSerializer(settings_obj).data)

    def _save(self, request, pk):
        site = get_object_or_404(self.filter_by_site_permission(Site.objects.all()), pk=pk)
        self.check_site_edit_permission(site)
        settings_obj, _ = SEOSettings.objects.get_or_create(site=site)
        serializer = SEOSettingsSerializer(settings_obj, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def update(self, request, pk=None):
        return self._save(request, pk)

    def partial_update(self, request, pk=None):
        return self._save(request, pk)


# ---------------------------------------------------------------------------
# SEO: LibreCrawl companion service
# ---------------------------------------------------------------------------

class LibreCrawlStatusView(SitePermissionMixin, APIView):
    """Return status and launch metadata for the vendored LibreCrawl service."""

    def get(self, request):
        site = self.get_site_from_request(key="site", source="query", require_edit=False)
        from .librecrawl_service import librecrawl_status

        return Response(librecrawl_status(site, request))


class SerpBearStatusView(SitePermissionMixin, APIView):
    """Return status and launch metadata for the vendored SerpBear service."""

    def get(self, request):
        site = self.get_site_from_request(key="site", source="query", require_edit=False)
        from .serpbear_service import serpbear_status

        return Response(serpbear_status(site))


class UmamiStatusView(SitePermissionMixin, APIView):
    """Return status and launch metadata for the vendored Umami service."""

    def get(self, request):
        site = self.get_site_from_request(key="site", source="query", require_edit=False)
        from .umami_service import umami_status

        return Response(umami_status(site))


class PayloadCMSStatusView(SitePermissionMixin, APIView):
    """Return status and launch metadata for the vendored Payload CMS companion."""

    def get(self, request):
        site = self.get_site_from_request(key="site", source="query", require_edit=False)
        from .payload_service import payload_cms_status

        return Response(payload_cms_status(site, request))


class PayloadEcommerceStatusView(SitePermissionMixin, APIView):
    """Return status and launch metadata for the vendored Payload ecommerce companion."""

    def get(self, request):
        site = self.get_site_from_request(key="site", source="query", require_edit=False)
        from .payload_service import payload_ecommerce_status

        return Response(payload_ecommerce_status(site, request))


# ---------------------------------------------------------------------------
# SEO: Google Search Console integration
# ---------------------------------------------------------------------------

class GSCConnectView(SitePermissionMixin, APIView):
    """Return the OAuth2 consent URL the frontend should redirect to."""

    def get(self, request):
        site = self.get_site_from_request(key="site", source="query", require_edit=True)
        from .seo_services import gsc_build_auth_url
        result = gsc_build_auth_url(site.id, request.user.id)
        if "error" in result:
            return Response(result, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response(result)


class GSCCallbackView(APIView):
    """Exchange OAuth2 code for tokens (called by frontend after consent)."""

    permission_classes = [permissions.AllowAny]

    def get(self, request):
        code = request.query_params.get("code", "")
        state = request.query_params.get("state", "")
        error = request.query_params.get("error", "")

        if error:
            return HttpResponse(
                f"<html><body><p>Google auth error: {error}</p>"
                "<script>window.close();</script></body></html>",
                content_type="text/html",
            )

        if not code or not state:
            return Response({"detail": "Missing code or state."}, status=status.HTTP_400_BAD_REQUEST)

        if not request.user.is_authenticated:
            return HttpResponse(
                "<html><body><p>Please sign in again before completing Google Search Console setup.</p>"
                "<script>window.close();</script></body></html>",
                content_type="text/html",
                status=status.HTTP_401_UNAUTHORIZED,
            )

        try:
            from .seo_services import gsc_parse_state

            state_payload = gsc_parse_state(state)
        except signing.SignatureExpired:
            return Response({"detail": "Google authorization expired. Try again."}, status=status.HTTP_400_BAD_REQUEST)
        except signing.BadSignature:
            return Response({"detail": "Invalid state parameter."}, status=status.HTTP_400_BAD_REQUEST)

        if request.user.id != state_payload["user_id"]:
            return Response({"detail": "OAuth session does not match the signed-in user."}, status=status.HTTP_403_FORBIDDEN)

        from .workspace_views import check_site_permission

        site_id = state_payload["site_id"]
        site = get_object_or_404(Site.objects.select_related("workspace"), pk=site_id)
        if not check_site_permission(request.user, site, require_edit=True):
            return Response({"detail": "You don't have permission to connect Search Console for this site."}, status=status.HTTP_403_FORBIDDEN)

        from .seo_services import gsc_exchange_code
        redirect_uri = request.build_absolute_uri("/api/seo/gsc/callback/")
        result = gsc_exchange_code(site_id, code, redirect_uri)

        if "error" in result:
            return HttpResponse(
                f"<html><body><p>Connection failed: {result['error']}</p>"
                "<script>window.close();</script></body></html>",
                content_type="text/html",
            )
        return HttpResponse(
            "<html><body><p>Google Search Console connected successfully!</p>"
            "<script>window.opener && window.opener.postMessage('gsc_connected','*'); window.close();</script>"
            "</body></html>",
            content_type="text/html",
        )


class GSCSyncView(SitePermissionMixin, APIView):
    """Fetch latest data from GSC and upsert into SEOAnalytics."""

    def post(self, request):
        days = int(request.data.get("days", 90))
        site = self.get_site_from_request(key="site", source="data", require_edit=True)
        from .seo_services import gsc_sync
        result = gsc_sync(site, days=days)
        if "error" in result:
            return Response(result, status=status.HTTP_400_BAD_REQUEST)
        return Response(result)


class GSCDisconnectView(SitePermissionMixin, APIView):
    """Remove stored GSC credentials for a site."""

    def post(self, request):
        site = self.get_site_from_request(key="site", source="data", require_edit=True)
        from .seo_services import gsc_disconnect
        gsc_disconnect(site)
        return Response({"ok": True})


class GSCStatusView(SitePermissionMixin, APIView):
    """Return GSC connection status and credential metadata for a site."""

    def get(self, request):
        site = self.get_site_from_request(key="site", source="query", require_edit=False)
        try:
            cred = site.gsc_credential
        except SearchConsoleCredential.DoesNotExist:
            return Response({"is_connected": False, "property_url": "", "last_synced_at": None, "sync_error": ""})
        return Response(SearchConsoleCredentialSerializer(cred).data)


class GSCPropertiesView(SitePermissionMixin, APIView):
    """List GSC properties the connected account can access."""

    def get(self, request):
        site = self.get_site_from_request(key="site", source="query", require_edit=False)
        from .seo_services import gsc_list_properties
        return Response({"properties": gsc_list_properties(site)})


class GSCCredentialUpdateView(SitePermissionMixin, APIView):
    """Update property_url on an existing GSC credential."""

    def patch(self, request):
        property_url = request.data.get("property_url", "")
        site = self.get_site_from_request(key="site", source="data", require_edit=True)
        cred, _ = SearchConsoleCredential.objects.get_or_create(site=site)
        cred.property_url = property_url
        cred.save(update_fields=["property_url", "updated_at"])
        return Response(SearchConsoleCredentialSerializer(cred).data)


def public_robots(request, site_slug: str):
    from .models import RobotsTxt
    ensure_seed_data()
    site = get_object_or_404(Site, slug=site_slug)
    
    try:
        robots = site.robots_txt
        if robots.is_custom:
            return HttpResponse(robots.content, content_type="text/plain")
    except RobotsTxt.DoesNotExist:
        pass
    
    sitemap_url = request.build_absolute_uri(f"/preview/{site.slug}/sitemap.xml")
    return HttpResponse(f"User-agent: *\nAllow: /\nSitemap: {sitemap_url}\n", content_type="text/plain")


# ---------------------------------------------------------------------------
# Payment Views
# ---------------------------------------------------------------------------

class PaymentConfigView(APIView):
    """Return payment configuration status for the platform."""
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        from .payment_services import get_payment_service, get_stripe_publishable_key, PaymentProvider

        service = get_payment_service()
        config_status = service.get_configuration_status()

        return Response({
            "stripe_configured": config_status.get("stripe", False),
            "publishable_key": get_stripe_publishable_key() if config_status.get("stripe") else "",
            "default_provider": "stripe",
            "providers": config_status,
        })


class PaymentIntentView(APIView):
    """Create a payment intent for an order."""
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        from .payment_services import (
            get_payment_service,
            get_stripe_publishable_key,
            PaymentError,
            PaymentConfigurationError,
        )

        payload = PaymentIntentSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        order_id = payload.validated_data["order_id"]

        try:
            order = Order.objects.get(pk=order_id)
        except Order.DoesNotExist:
            return Response(
                {"detail": "Order not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            _check_checkout_order_access(request, order)
        except PermissionDenied as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)

        # Check if order is already paid
        if order.payment_status == Order.PAYMENT_PAID:
            return Response(
                {"detail": "Order is already paid."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        service = get_payment_service()

        # Check if payment is configured
        if not service.is_payment_configured():
            return Response(
                {
                    "detail": "Payment processing is not configured. Please contact the administrator.",
                    "code": "payment_not_configured",
                    "requires_configuration": True,
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        try:
            intent = service.create_checkout_session(order)
            log_security_event(
                "payment.intent.create",
                request=request,
                actor=request.user if request.user.is_authenticated else None,
                target_type="order",
                target_id=str(order.pk),
                metadata={"amount": intent.amount, "currency": intent.currency},
            )
            return Response({
                "client_secret": intent.client_secret,
                "payment_intent_id": intent.intent_id,
                "amount": intent.amount,
                "currency": intent.currency,
                "publishable_key": get_stripe_publishable_key(),
            })
        except PaymentConfigurationError as e:
            return Response(
                {
                    "detail": str(e),
                    "code": "payment_not_configured",
                    "requires_configuration": True,
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except PaymentError as e:
            return Response(
                {"detail": str(e), "code": e.code},
                status=status.HTTP_400_BAD_REQUEST,
            )


class PaymentWebhookView(APIView):
    """Handle payment provider webhooks (Stripe)."""
    permission_classes = [permissions.AllowAny]
    throttle_classes = []

    def get_throttles(self):
        from .throttles import WebhookThrottle
        return [WebhookThrottle()]

    def post(self, request):
        from .payment_services import (
            get_payment_service,
            PaymentProvider,
            PaymentError,
        )

        # Get Stripe signature header
        signature = request.META.get("HTTP_STRIPE_SIGNATURE", "")
        if not signature:
            return Response(
                {"detail": "Missing Stripe signature."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        service = get_payment_service()

        try:
            event = service.process_webhook_event(
                PaymentProvider.STRIPE,
                request.body,
                signature,
            )
            return Response({"received": True, "type": event.get("type", "")})
        except PaymentError as e:
            return Response(
                {"detail": str(e), "code": e.code},
                status=status.HTTP_400_BAD_REQUEST,
            )


class OrderPaymentStatusView(APIView):
    """Check payment status for an order."""
    permission_classes = [permissions.AllowAny]

    def get(self, request, order_id: int):
        try:
            order = Order.objects.get(pk=order_id)
        except Order.DoesNotExist:
            return Response(
                {"detail": "Order not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            _check_checkout_order_access(request, order)
        except PermissionDenied as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)

        return Response({
            "order_id": order.id,
            "order_number": order.order_number,
            "status": order.status,
            "payment_status": order.payment_status,
            "total": str(order.total),
            "currency": order.currency,
        })


class RefundOrderView(APIView):
    """Refund an order (admin only)."""

    def post(self, request, order_id: int):
        from .payment_services import get_payment_service, PaymentError

        try:
            order = Order.objects.get(pk=order_id)
        except Order.DoesNotExist:
            return Response(
                {"detail": "Order not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            _check_checkout_order_access(request, order, require_manage=True)
        except PermissionDenied as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)

        if order.payment_status != Order.PAYMENT_PAID:
            return Response(
                {"detail": "Order is not paid and cannot be refunded."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not order.payment_reference:
            return Response(
                {"detail": "Order has no payment reference for refund."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        service = get_payment_service()

        try:
            result = service.refund_order(order)
            if result.success:
                log_security_event(
                    "payment.refund.success",
                    request=request,
                    actor=request.user if request.user.is_authenticated else None,
                    target_type="order",
                    target_id=str(order.pk),
                    metadata={"refund_id": result.refund_id, "amount": result.amount},
                )
                return Response({
                    "success": True,
                    "refund_id": result.refund_id,
                    "amount": result.amount,
                    "order_status": order.status,
                    "payment_status": order.payment_status,
                })
            else:
                log_security_event(
                    "payment.refund.failed",
                    request=request,
                    actor=request.user if request.user.is_authenticated else None,
                    target_type="order",
                    target_id=str(order.pk),
                    success=False,
                    metadata={"error": result.error_message},
                )
                return Response(
                    {"detail": result.error_message, "success": False},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        except PaymentError as e:
            log_security_event(
                "payment.refund.failed",
                request=request,
                actor=request.user if request.user.is_authenticated else None,
                target_type="order",
                target_id=str(order.pk),
                success=False,
                metadata={"error_code": e.code},
            )
            return Response(
                {"detail": str(e), "code": e.code},
                status=status.HTTP_400_BAD_REQUEST,
            )
