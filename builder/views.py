from django.contrib.auth import authenticate, get_user_model, login, logout
from django.conf import settings
from django.core import signing
from django.db import models
from django.http import Http404, HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.utils.decorators import method_decorator
from django.utils import timezone
from django.utils.html import strip_tags
from django.contrib.syndication.views import Feed
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import permissions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from .commerce_runtime import calculate_cart_pricing, shipping_country_for, shipping_state_for


class SiteObjectPermission(permissions.BasePermission):
    """Enforce view/edit access for site-scoped detail objects."""

    message = "You don't have permission to access this site."

    def has_object_permission(self, request, view, obj):
        if not hasattr(view, "get_site_for_object"):
            return True
        site = view.get_site_for_object(obj)
        if site is None:
            return False
        from .workspace_views import check_site_permission

        require_edit = request.method not in permissions.SAFE_METHODS
        return check_site_permission(request.user, site, require_edit=require_edit)


class SitePermissionMixin:
    """Mixin to filter querysets by user's workspace permissions."""

    site_lookup_field = "site"
    permission_classes = [permissions.IsAuthenticated, SiteObjectPermission]

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
        user = self.request.user
        if user.is_superuser:
            return queryset
        if not user.is_authenticated:
            return queryset.none()
        # Get accessible site IDs
        accessible_sites = filter_sites_by_permission(user, Site.objects.all())
        return queryset.filter(**{f"{self.site_lookup_field}__in": accessible_sites}).distinct()

    def get_site_from_request(self, *, key: str = "site", source: str = "query", require_edit: bool = False):
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
            from .workspace_views import check_site_permission

            if not check_site_permission(self.request.user, site, require_edit=False):
                raise PermissionDenied("You don't have permission to access this site.")
        return site

    def check_site_edit_permission(self, site):
        """Check if user can edit content on this site."""
        from .workspace_views import check_site_permission
        if not check_site_permission(self.request.user, site, require_edit=True):
            raise PermissionDenied("You don't have permission to edit this site.")

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
from .serializers import (
    AuthBootstrapSerializer,
    AuthLoginSerializer,
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
    PublicCommentSubmissionSerializer,
    PublicCartAddSerializer,
    PublicCartItemUpdateSerializer,
    PublicCheckoutSerializer,
    PublicFormSubmissionSerializer,
    PostCategorySerializer,
    PostSerializer,
    PostTagSerializer,
    ProductCategorySerializer,
    ProductSerializer,
    ProductVariantSerializer,
    PublicCartPricingSerializer,
    KeywordRankEntrySerializer,
    SearchConsoleCredentialSerializer,
    SEOAnalyticsSerializer,
    SEOAuditSerializer,
    SEOSettingsSerializer,
    ShippingRateSerializer,
    ShippingZoneSerializer,
    SiteSerializer,
    SiteLocaleSerializer,
    SiteMirrorImportSerializer,
    TaxRateSerializer,
    TrackedKeywordSerializer,
    URLRedirectSerializer,
    WebhookSerializer,
    WorkspaceSerializer,
    WorkspaceMembershipSerializer,
    WorkspaceInvitationSerializer,
    InviteMemberSerializer,
    ChangeMemberRoleSerializer,
    CollaboratorUserSerializer,
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
from .search_services import search_service


User = get_user_model()


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

        if search_service.enabled:
            results = self._search_meilisearch(query, site_map, limit, request)
            if results:
                backend_name = "meilisearch"

        if not results:
            results = self._search_database(query, site_map, limit, request)

        return Response({"results": results[:limit], "query": query, "backend": backend_name})

    def _search_meilisearch(self, query: str, site_map: dict[int, Site], limit: int, request) -> list[dict[str, object]]:
        search_service.setup_indexes()
        raw_results = search_service.search_all(query, site_id=None, limit_per_index=max(1, min(limit, 5)))
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
        return {
            "id": f"page_{page.id}",
            "type": "page",
            "title": page.title,
            "excerpt": _truncate_text(page.html or page.seo.get("meta_description", "") or page.path),
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
        return Response(
            {
                "authenticated": bool(user),
                "has_users": User.objects.exists(),
                "user": (
                    {
                        "username": user.username,
                        "email": user.email,
                        "is_superuser": user.is_superuser,
                    }
                    if user
                    else None
                ),
            }
        )


class AuthBootstrapView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        from django.db import transaction, IntegrityError

        serializer = AuthBootstrapSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            with transaction.atomic():
                # Use select_for_update to lock and prevent race condition
                # Check inside transaction to ensure atomicity
                if User.objects.select_for_update().exists():
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
            return Response(
                {"detail": "Bootstrap is disabled after the first user is created."},
                status=status.HTTP_400_BAD_REQUEST
            )

        login(request, user)
        return Response(
            {
                "authenticated": True,
                "has_users": True,
                "user": {
                    "username": user.username,
                    "email": user.email,
                    "is_superuser": user.is_superuser,
                },
            },
            status=status.HTTP_201_CREATED,
        )


class AuthLoginView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = AuthLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = authenticate(
            request,
            username=serializer.validated_data["username"],
            password=serializer.validated_data["password"],
        )
        if not user:
            return Response({"detail": "Invalid username or password."}, status=status.HTTP_400_BAD_REQUEST)

        login(request, user)
        return Response(
            {
                "authenticated": True,
                "has_users": True,
                "user": {
                    "username": user.username,
                    "email": user.email,
                    "is_superuser": user.is_superuser,
                },
            }
        )


class AuthLogoutView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        logout(request)
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


class MetricsView(APIView):
    """Basic metrics endpoint for monitoring."""
    permission_classes = [permissions.AllowAny]

    def get(self, request):
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

        return Response(metrics)


class AuthMagicLoginView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        if not settings.DEBUG:
            raise Http404("Not available")

        username = (request.query_params.get("username") or "").strip()
        if not username:
            return Response({"detail": "username is required."}, status=status.HTTP_400_BAD_REQUEST)

        user = get_object_or_404(User, username=username)
        login(request, user)

        next_url = request.query_params.get("next") or ""
        if next_url:
            return HttpResponseRedirect(next_url)

        return Response(
            {
                "authenticated": True,
                "has_users": True,
                "user": {
                    "username": user.username,
                    "email": user.email,
                    "is_superuser": user.is_superuser,
                },
            }
        )


class SiteViewSet(SitePermissionMixin, viewsets.ModelViewSet):
    serializer_class = SiteSerializer

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
        search_service.index_page(page)

    def perform_update(self, serializer):
        page = super().perform_update(serializer)
        search_service.index_page(page)

    @action(detail=True, methods=["post"])
    def save_builder(self, request, pk=None):
        page = self.get_object()
        serializer = BuilderSaveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        build_page_payload(page, serializer.validated_data)
        sync_homepage_state(page)
        try:
            ensure_unique_page_path(page)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        page.status = Page.STATUS_DRAFT
        page.save()
        create_revision(page, "Draft snapshot")
        search_service.index_page(page)
        return Response(PageSerializer(page, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def publish(self, request, pk=None):
        page = self.get_object()
        serializer = BuilderSaveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        build_page_payload(page, serializer.validated_data)
        sync_homepage_state(page)
        try:
            ensure_unique_page_path(page)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        page.status = Page.STATUS_PUBLISHED
        page.published_at = timezone.now()
        page.save()
        create_revision(page, "Published snapshot")
        search_service.index_page(page)
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
        search_service.index_page(translation.page)

    def perform_update(self, serializer):
        translation = super().perform_update(serializer)
        search_service.index_page(translation.page)

    def perform_destroy(self, instance):
        page = instance.page
        super().perform_destroy(instance)
        search_service.index_page(page)

    @action(detail=True, methods=["post"])
    def save_builder(self, request, pk=None):
        translation = self.get_object()
        serializer = BuilderSaveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        build_translation_payload(translation, serializer.validated_data)
        try:
            PageTranslationSerializer(instance=translation, data={"page": translation.page_id, "locale": translation.locale_id, "slug": translation.slug, "title": translation.title}, partial=True).is_valid(raise_exception=True)
        except serializers.ValidationError as exc:
            return Response(exc.detail, status=status.HTTP_400_BAD_REQUEST)

        translation.status = PageTranslation.STATUS_DRAFT
        translation.save()
        search_service.index_page(translation.page)
        return Response(PageTranslationSerializer(translation, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def publish(self, request, pk=None):
        translation = self.get_object()
        serializer = BuilderSaveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        build_translation_payload(translation, serializer.validated_data)
        try:
            PageTranslationSerializer(instance=translation, data={"page": translation.page_id, "locale": translation.locale_id, "slug": translation.slug, "title": translation.title}, partial=True).is_valid(raise_exception=True)
        except serializers.ValidationError as exc:
            return Response(exc.detail, status=status.HTTP_400_BAD_REQUEST)

        translation.status = PageTranslation.STATUS_PUBLISHED
        translation.published_at = timezone.now()
        translation.save()
        search_service.index_page(translation.page)
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
        page.builder_data = revision.snapshot or {}
        page.html = revision.html or ""
        page.css = revision.css or ""
        page.js = revision.js or ""
        page.status = Page.STATUS_DRAFT
        page.save(update_fields=["builder_data", "html", "css", "js", "status", "updated_at"])
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
        if site_id:
            queryset = queryset.filter(site_id=site_id)
        if folder_id:
            queryset = queryset.filter(folder_id=folder_id)
        if unfoldered in {"1", "true", "yes"}:
            queryset = queryset.filter(folder__isnull=True)
        if kind:
            queryset = queryset.filter(kind=kind)
        if search:
            queryset = queryset.filter(
                models.Q(title__icontains=search) | models.Q(alt_text__icontains=search)
            )
        return self.filter_by_site_permission(queryset)

    def perform_create(self, serializer):
        asset = super().perform_create(serializer)
        search_service.index_media(asset)

    def perform_update(self, serializer):
        asset = super().perform_update(serializer)
        search_service.index_media(asset)

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
                request.data._mutable = True
                request.data["kind"] = kind
                request.data._mutable = False

        return super().create(request, *args, **kwargs)

    @action(detail=False, methods=["post"])
    def bulk_delete(self, request):
        ids = request.data.get("ids", [])
        if not ids:
            return Response({"detail": "Provide 'ids' list."}, status=status.HTTP_400_BAD_REQUEST)
        assets = MediaAsset.objects.filter(pk__in=ids)
        for asset in assets:
            try:
                asset.file.delete(save=False)
            except Exception:
                pass
        count, _ = assets.delete()
        return Response({"deleted": count})

    @action(detail=False, methods=["post"])
    def move_to_folder(self, request):
        ids = request.data.get("ids", [])
        folder_id = request.data.get("folder_id")
        if not ids:
            return Response({"detail": "Provide 'ids' list."}, status=status.HTTP_400_BAD_REQUEST)
        folder = None
        if folder_id:
            folder = get_object_or_404(MediaFolder, pk=folder_id)
        updated = MediaAsset.objects.filter(pk__in=ids).update(folder=folder)
        return Response({"moved": updated})


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
            Post.objects.select_related("site", "featured_media")
            .prefetch_related("categories", "tags", "comments")
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
        search_service.index_post(post)

    def perform_update(self, serializer):
        post = super().perform_update(serializer)
        search_service.index_post(post)

    @action(detail=True, methods=["post"])
    def publish(self, request, pk=None):
        post = self.get_object()
        post.status = Post.STATUS_PUBLISHED
        post.published_at = timezone.now()
        post.save(update_fields=["status", "published_at", "updated_at"])
        search_service.index_post(post)
        trigger_webhooks(post.site, "post.published", {"post_id": post.id, "title": post.title, "slug": post.slug})
        return Response(PostSerializer(post, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def unpublish(self, request, pk=None):
        post = self.get_object()
        post.status = Post.STATUS_DRAFT
        post.save(update_fields=["status", "updated_at"])
        search_service.index_post(post)
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
        post.save(update_fields=["scheduled_at", "updated_at"])

        from .jobs import schedule_content_publish
        schedule_content_publish("post", post.id, scheduled_time)

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
        search_service.index_product(product)

    def perform_update(self, serializer):
        product = super().perform_update(serializer)
        search_service.index_product(product)

    @action(detail=True, methods=["post"])
    def publish(self, request, pk=None):
        product = self.get_object()
        product.status = Product.STATUS_PUBLISHED
        product.published_at = timezone.now()
        product.save(update_fields=["status", "published_at", "updated_at"])
        search_service.index_product(product)
        return Response(ProductSerializer(product, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def unpublish(self, request, pk=None):
        product = self.get_object()
        product.status = Product.STATUS_DRAFT
        product.save(update_fields=["status", "updated_at"])
        search_service.index_product(product)
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
        comment.save(update_fields=["is_approved", "updated_at"])
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
            payload=serializer.validated_data["payload"],
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
        comment = Comment.objects.create(
            post=post,
            author_name=serializer.validated_data["author_name"],
            author_email=serializer.validated_data["author_email"],
            body=serializer.validated_data["body"],
            is_approved=False,
        )
        return Response(
            {
                "id": comment.id,
                "detail": "Comment received and queued for moderation.",
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
    payload = {
        "title": translation.title if translation else page.title,
        "seo": translation.seo if translation else page.seo,
        "page_settings": translation.page_settings if translation else page.page_settings,
        "builder_data": translation.builder_data if translation else page.builder_data,
        "html": translation.html if translation else page.html,
        "css": translation.css if translation else page.css,
        "js": translation.js if translation else page.js,
    }
    experiment_context = evaluate_page_experiments(request, page, translation.locale if translation else locale)
    payload = apply_variant_to_page_payload(payload, experiment_context["assignments"])

    if payload["page_settings"].get("document_mode") == "full_html" and str(payload["html"]).lstrip().lower().startswith("<!doctype html"):
        response = HttpResponse(payload["html"], content_type="text/html; charset=utf-8")
        return persist_experiment_cookies(
            response,
            experiment_context["visitor_id"],
            experiment_context["assignment_cookie"],
            visitor_cookie_changed=experiment_context["visitor_cookie_changed"],
            assignment_cookie_changed=experiment_context["assignment_cookie_changed"],
        )

    meta_title = payload["seo"].get("meta_title") or f"{site.name} | {payload['title']}"
    meta_description = payload["seo"].get("meta_description") or site.tagline or site.description or payload["title"]
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
        template.status = BT.STATUS_PUBLISHED
        template.save(update_fields=["status", "updated_at"])
        return Response(BlockTemplateSerializer(template, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def unpublish(self, request, pk=None):
        from .models import BlockTemplate as BT
        template = self.get_object()
        template.status = BT.STATUS_DRAFT
        template.save(update_fields=["status", "updated_at"])
        return Response(BlockTemplateSerializer(template, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def submit_to_marketplace(self, request, pk=None):
        from .models import BlockTemplate as BT
        template = self.get_object()
        template.status = BT.STATUS_MARKETPLACE
        template.is_global = True
        template.save(update_fields=["status", "is_global", "updated_at"])
        return Response(BlockTemplateSerializer(template, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def disable(self, request, pk=None):
        from .models import BlockTemplate as BT
        template = self.get_object()
        template.status = BT.STATUS_DISABLED
        template.save(update_fields=["status", "updated_at"])
        return Response(BlockTemplateSerializer(template, context={"request": request}).data)


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

        order_id = request.data.get("order_id")
        if not order_id:
            return Response(
                {"detail": "order_id is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

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
                return Response({
                    "success": True,
                    "refund_id": result.refund_id,
                    "amount": result.amount,
                    "order_status": order.status,
                    "payment_status": order.payment_status,
                })
            else:
                return Response(
                    {"detail": result.error_message, "success": False},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        except PaymentError as e:
            return Response(
                {"detail": str(e), "code": e.code},
                status=status.HTTP_400_BAD_REQUEST,
            )
