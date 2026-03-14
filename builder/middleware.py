import logging

from django.http import HttpResponsePermanentRedirect, HttpResponseRedirect
from django.utils.deprecation import MiddlewareMixin

from .models import URLRedirect

logger = logging.getLogger(__name__)


class RedirectMiddleware(MiddlewareMixin):
    def process_request(self, request):
        if request.method != "GET":
            return None

        path = request.path_info

        # Skip Django admin and API paths — they are never subject to site redirects.
        if path.startswith("/admin/") or path.startswith("/api/"):
            return None

        host = request.get_host().split(":")[0].lower()

        try:
            # Prefer a redirect scoped to the site whose domain matches the Host header.
            # Fall back to a redirect whose site has no domain set (blank/null) so that
            # local dev single-site installs still work.
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
                        site__domain="",
                    )
                    .first()
                )

            if redirect:
                redirect.hit_count += 1
                redirect.save(update_fields=["hit_count", "updated_at"])

                if redirect.redirect_type == URLRedirect.TYPE_PERMANENT:
                    return HttpResponsePermanentRedirect(redirect.target_path)
                else:
                    return HttpResponseRedirect(redirect.target_path)
        except Exception:
            logger.exception("RedirectMiddleware error for path %s", path)

        return None
