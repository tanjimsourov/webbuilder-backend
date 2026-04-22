from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path, re_path

from blog.views import (
    SiteBlogFeed,
    public_blog_index,
    public_blog_post,
)
from cms.views import (
    public_page,
    public_robots,
    public_sitemap,
)
from commerce.views import (
    public_shop_cart,
    public_shop_index,
    public_shop_product,
)


urlpatterns = [
    path("api/", include("core.urls")),
    path("api/", include("cms.urls")),
    path("api/", include("blog.urls")),
    path("api/", include("forms.urls")),
    path("api/", include("commerce.urls")),
    path("api/", include("domains.urls")),
    path("api/", include("analytics.urls")),
    path("api/", include("notifications.urls")),
    path("api/", include("website.urls")),
    path("api/", include("provider.urls")),
    path("api/payments/", include(("payments.urls", "payments"), namespace="payments")),
    path("api/email-hosting/", include(("email_hosting.urls", "email_hosting"), namespace="email_hosting")),
    path("api/", include("builder.urls")),
    path("preview/<slug:site_slug>/feed.xml", SiteBlogFeed(), name="preview-blog-feed"),
    path("preview/<slug:site_slug>/sitemap.xml", public_sitemap, name="preview-sitemap"),
    path("preview/<slug:site_slug>/robots.txt", public_robots, name="preview-robots"),
    path("preview/<slug:site_slug>/blog/", public_blog_index, name="preview-blog-index"),
    path("preview/<slug:site_slug>/blog/<slug:post_slug>/", public_blog_post, name="preview-blog-post"),
    path("preview/<slug:site_slug>/shop/", public_shop_index, name="preview-shop-index"),
    path("preview/<slug:site_slug>/shop/cart/", public_shop_cart, name="preview-shop-cart"),
    path("preview/<slug:site_slug>/shop/<slug:product_slug>/", public_shop_product, name="preview-shop-product"),
    re_path(
        r"^preview/(?P<site_slug>[-\w]+)/(?P<locale_code>[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})?)/?$",
        public_page,
        {"page_path": ""},
        name="preview-home-localized",
    ),
    re_path(
        r"^preview/(?P<site_slug>[-\w]+)/(?P<locale_code>[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})?)/(?P<page_path>.*)$",
        public_page,
        name="preview-page-localized",
    ),
    re_path(r"^preview/(?P<site_slug>[-\w]+)/?$", public_page, {"page_path": ""}, name="preview-home"),
    re_path(r"^preview/(?P<site_slug>[-\w]+)/(?P<page_path>.*)$", public_page, name="preview-page"),
]

if settings.ENABLE_ADMIN:
    urlpatterns.insert(0, path("admin/", admin.site.urls))

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
