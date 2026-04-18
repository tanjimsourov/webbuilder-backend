import logging

from django.conf import settings
from django.http import HttpResponseNotFound, HttpResponsePermanentRedirect, HttpResponseRedirect
from django.utils.deprecation import MiddlewareMixin
from django.utils.http import url_has_allowed_host_and_scheme

from .models import URLRedirect

logger = logging.getLogger(__name__)


class AdminAccessMiddleware(MiddlewareMixin):
    def process_request(self, request):
        if request.path_info.startswith("/admin/") and not getattr(settings, "ENABLE_ADMIN", settings.DEBUG):
            return HttpResponseNotFound("Not Found")
        return None


class RedirectMiddleware(MiddlewareMixin):
    def _is_safe_redirect_target(self, target: str, host: str) -> bool:
        target_value = (target or "").strip()
        if not target_value:
            return False
        if target_value.startswith("/"):
            return not target_value.startswith("//")

        allowed_hosts = {host, *getattr(settings, "REDIRECT_ALLOWED_EXTERNAL_HOSTS", [])}
        return url_has_allowed_host_and_scheme(
            target_value,
            allowed_hosts=allowed_hosts,
            require_https=not settings.DEBUG,
        )

    def process_request(self, request):
        if request.method != "GET":
            return None

        path = request.path_info
        if path.startswith("/admin/") or path.startswith("/api/"):
            return None

        try:
            host = request.get_host().split(":")[0].lower()
            redirect = (
                URLRedirect.objects.select_related("site")
                .filter(source_path=path, status=URLRedirect.STATUS_ACTIVE)
                .filter(site__domain__iexact=host)
                .first()
            )

            if redirect is None:
                redirect = (
                    URLRedirect.objects.select_related("site")
                    .filter(
                        source_path=path,
                        status=URLRedirect.STATUS_ACTIVE,
                        site__domain__in=["", None],
                    )
                    .first()
                )

            if redirect:
                if not self._is_safe_redirect_target(redirect.target_path, host):
                    logger.warning("Skipping unsafe redirect target for source path %s", path)
                    return None

                redirect.hit_count += 1
                redirect.save(update_fields=["hit_count", "updated_at"])

                if redirect.redirect_type == URLRedirect.TYPE_PERMANENT:
                    return HttpResponsePermanentRedirect(redirect.target_path)
                return HttpResponseRedirect(redirect.target_path)
        except Exception:
            logger.exception("RedirectMiddleware error for path %s", path)

        return None
