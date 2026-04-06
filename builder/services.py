from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable
from uuid import uuid4

from django.conf import settings
from django.utils import timezone
from django.utils.text import slugify

from cms.page_schema import (
    default_renderer_key_for_block_category,
    normalize_block_template_builder_data,
    normalize_page_content,
)

from .commerce_runtime import calculate_cart_pricing
from .localization import localized_preview_url, sync_translation_paths
from .models import (
    BlockTemplate,
    Cart,
    CartItem,
    DiscountCode,
    FormSubmission,
    Order,
    OrderItem,
    Page,
    PageRevision,
    Post,
    PostCategory,
    PostTag,
    Product,
    ProductCategory,
    ProductVariant,
    ShippingRate,
    ShippingZone,
    Site,
    TaxRate,
)


BASE_BLOCK_CSS = """
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--wb-canvas);
  color: var(--wb-text);
  font-family: var(--wb-body-font);
}
a { color: inherit; }
img { max-width: 100%; display: block; }
.wb-shell {
  width: min(var(--wb-width), calc(100% - 48px));
  margin: 0 auto;
}
.wb-section {
  padding: 88px 0;
}
.wb-grid {
  display: grid;
  gap: 24px;
}
.wb-grid-2 {
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
}
.wb-grid-3 {
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
}
.wb-card {
  border-radius: var(--wb-radius);
  padding: 28px;
  background: rgba(255, 255, 255, 0.84);
  border: 1px solid rgba(15, 23, 42, 0.08);
  box-shadow: 0 26px 80px rgba(15, 23, 42, 0.08);
}
.wb-hero {
  padding: 100px 0 72px;
}
.wb-hero-panel {
  background:
    radial-gradient(circle at top left, rgba(59, 130, 246, 0.22), transparent 36%),
    radial-gradient(circle at bottom right, rgba(20, 184, 166, 0.16), transparent 30%),
    rgba(255, 255, 255, 0.92);
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: calc(var(--wb-radius) * 1.3);
  padding: 56px;
  box-shadow: 0 32px 100px rgba(15, 23, 42, 0.1);
}
.wb-eyebrow {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  font-size: 12px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: var(--wb-brand);
  font-weight: 700;
}
.wb-hero h1,
.wb-section h2,
.wb-section h3 {
  font-family: var(--wb-heading-font);
  line-height: 0.98;
  margin: 0;
  color: #081120;
}
.wb-hero h1 {
  font-size: clamp(3.4rem, 7vw, 6.6rem);
  margin-top: 18px;
}
.wb-hero p,
.wb-section p,
.wb-list li {
  font-size: 1.05rem;
  line-height: 1.72;
  color: rgba(8, 17, 32, 0.78);
}
.wb-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  margin-top: 28px;
}
.wb-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 50px;
  padding: 0 22px;
  border-radius: 999px;
  text-decoration: none;
  font-weight: 700;
  transition: transform 160ms ease, box-shadow 160ms ease;
}
.wb-button:hover {
  transform: translateY(-1px);
}
.wb-button-primary {
  color: white;
  background: linear-gradient(135deg, var(--wb-brand), color-mix(in srgb, var(--wb-brand) 68%, white 32%));
  box-shadow: 0 18px 30px color-mix(in srgb, var(--wb-brand) 24%, transparent);
}
.wb-button-secondary {
  color: #081120;
  background: rgba(255, 255, 255, 0.88);
  border: 1px solid rgba(8, 17, 32, 0.08);
}
.wb-metric {
  padding-top: 14px;
  border-top: 1px solid rgba(8, 17, 32, 0.12);
}
.wb-metric strong {
  display: block;
  font-size: 2rem;
  color: #081120;
}
.wb-surface {
  background: rgba(255, 255, 255, 0.88);
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: calc(var(--wb-radius) * 1.1);
}
.wb-stack {
  display: grid;
  gap: 16px;
}
.wb-list {
  display: grid;
  gap: 14px;
  padding-left: 18px;
}
.wb-price {
  font-size: 2.8rem;
  font-family: var(--wb-heading-font);
}
.wb-center {
  text-align: center;
}
.wb-badge {
  display: inline-flex;
  padding: 8px 14px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--wb-brand) 12%, white 88%);
  color: var(--wb-brand);
  font-weight: 700;
  font-size: 0.85rem;
}
.wb-footer {
  padding: 36px 0 60px;
  color: rgba(8, 17, 32, 0.62);
}
@media (max-width: 768px) {
  .wb-shell {
    width: min(var(--wb-width), calc(100% - 24px));
  }
  .wb-section {
    padding: 68px 0;
  }
  .wb-hero-panel {
    padding: 32px 24px;
  }
}
""".strip()


def default_theme() -> dict:
    return {
        "brandColor": "#2463eb",
        "accentColor": "#14b8a6",
        "surfaceColor": "#ffffff",
        "canvasColor": "#eef4ff",
        "textColor": "#0f172a",
        "headingFont": "'Space Grotesk', sans-serif",
        "bodyFont": "'IBM Plex Sans', sans-serif",
        "radius": "24px",
        "contentWidth": "1180px",
    }


def build_theme_css(theme: dict | None) -> str:
    values = {**default_theme(), **(theme or {})}
    return f"""
    :root {{
      --wb-brand: {values["brandColor"]};
      --wb-accent: {values["accentColor"]};
      --wb-surface: {values["surfaceColor"]};
      --wb-canvas: {values["canvasColor"]};
      --wb-text: {values["textColor"]};
      --wb-heading-font: {values["headingFont"]};
      --wb-body-font: {values["bodyFont"]};
      --wb-radius: {values["radius"]};
      --wb-width: {values["contentWidth"]};
    }}
    """.strip()


def preview_url_for_page(page: Page) -> str:
    return localized_preview_url(page.site.slug, page.path, is_homepage=page.is_homepage)


def preview_url_for_page_translation(translation) -> str:
    return localized_preview_url(
        translation.page.site.slug,
        translation.path,
        locale_code=translation.locale.code,
        is_homepage=translation.page.is_homepage,
    )


def preview_url_for_post(post: Post) -> str:
    return f"/preview/{post.site.slug}/blog/{post.slug}/"


def preview_url_for_product(product: Product) -> str:
    return f"/preview/{product.site.slug}/shop/{product.slug}/"


def normalize_page_path(slug: str, is_homepage: bool) -> str:
    if is_homepage:
        return "/"
    clean_slug = slug.strip("/") or "page"
    return f"/{clean_slug}/"


def build_page_payload(page: Page, payload: dict) -> None:
    if "title" in payload:
        page.title = payload["title"]

    page.is_homepage = payload.get("is_homepage", page.is_homepage)
    page.slug = slugify(payload.get("slug", page.slug) or page.title) or "page"
    page.path = normalize_page_path(page.slug, page.is_homepage)

    if "seo" in payload:
        page.seo = payload["seo"] or {}
    if "page_settings" in payload:
        page.page_settings = payload["page_settings"] or {}
    if "builder_schema_version" in payload:
        page.builder_schema_version = payload["builder_schema_version"]
    if "builder_data" in payload:
        page.builder_data = payload["builder_data"] or {}
    if "project_data" in payload:
        page.builder_data = payload["project_data"] or {}
    if "html" in payload:
        page.html = payload["html"] or ""
    if "css" in payload:
        page.css = payload["css"] or ""
    if "js" in payload:
        page.js = payload["js"] or ""

    strict_schema_validation = any(
        key in payload for key in ("builder_data", "project_data", "seo", "page_settings", "builder_schema_version")
    )
    normalized = normalize_page_content(
        title=page.title,
        slug=page.slug,
        path=page.path,
        is_homepage=page.is_homepage,
        status=page.status,
        locale_code="",
        builder_data=page.builder_data,
        seo=page.seo,
        page_settings=page.page_settings,
        html=page.html,
        css=page.css,
        js=page.js,
        schema_version=page.builder_schema_version,
        strict=strict_schema_validation,
    )
    page.builder_schema_version = normalized["schema_version"]
    page.builder_data = normalized["builder_data"]
    page.seo = normalized["seo"]
    page.page_settings = normalized["page_settings"]
    page.html = normalized["html"]
    page.css = normalized["css"]
    page.js = normalized["js"]


def ensure_unique_page_path(page: Page) -> None:
    query = Page.objects.filter(site=page.site, path=page.path)
    if page.pk:
        query = query.exclude(pk=page.pk)
    if query.exists():
        raise ValueError("Another page already uses this path.")


def sync_homepage_state(page: Page) -> None:
    if page.is_homepage:
        previous_homepage = Page.objects.filter(site=page.site, is_homepage=True).exclude(pk=page.pk).first()
        if previous_homepage:
            previous_homepage.is_homepage = False
            previous_homepage.path = normalize_page_path(previous_homepage.slug, False)
            previous_homepage.save(update_fields=["is_homepage", "path", "updated_at"])
            sync_translation_paths(previous_homepage)
        sync_translation_paths(page)
        return

    has_other_homepage = Page.objects.filter(site=page.site, is_homepage=True).exclude(pk=page.pk).exists()
    if not has_other_homepage:
        page.is_homepage = True
        page.path = "/"
    sync_translation_paths(page)


def create_revision(page: Page, label: str) -> PageRevision:
    return PageRevision.objects.create(
        page=page,
        label=label,
        builder_schema_version=page.builder_schema_version,
        snapshot=page.builder_data or {},
        html=page.html or "",
        css=page.css or "",
        js=page.js or "",
    )


def quantize_money(value: Decimal | int | float | str) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def resolve_variant(product: Product, variant_id: int | None = None) -> ProductVariant:
    variants = product.variants.filter(is_active=True)
    if variant_id:
        return variants.get(pk=variant_id)
    variant = variants.order_by("-is_default", "title").first()
    if variant is None:
        raise ProductVariant.DoesNotExist("No active variant is available for this product.")
    return variant


def ensure_variant_inventory(variant: ProductVariant, quantity: int) -> None:
    if quantity < 1:
        raise ValueError("Quantity must be at least 1.")
    if variant.track_inventory and quantity > variant.inventory:
        raise ValueError(f"Only {variant.inventory} units are available for {variant.title}.")


def sync_cart_item(cart_item: CartItem) -> CartItem:
    variant = cart_item.product_variant
    cart_item.unit_price = quantize_money(variant.price)
    cart_item.line_total = quantize_money(variant.price * cart_item.quantity)
    return cart_item


def recalculate_cart(cart: Cart) -> Cart:
    subtotal = Decimal("0.00")
    for item in cart.items.select_related("product_variant").all():
        sync_cart_item(item)
        item.save(update_fields=["unit_price", "line_total", "updated_at"])
        subtotal += item.line_total

    cart.subtotal = quantize_money(subtotal)
    cart.total = quantize_money(subtotal)
    cart.save(update_fields=["subtotal", "total", "updated_at"])
    return cart


def get_or_create_cart(site: Site, session) -> Cart:
    if not session.session_key:
        session.create()

    cart, _ = Cart.objects.get_or_create(
        site=site,
        session_key=session.session_key,
        status=Cart.STATUS_OPEN,
        defaults={"currency": "USD"},
    )
    return recalculate_cart(cart)


def build_order_number() -> str:
    return f"WB-{timezone.now():%Y%m%d}-{uuid4().hex[:8].upper()}"


def create_order_from_cart(
    cart: Cart,
    *,
    customer_name: str,
    customer_email: str,
    customer_phone: str = "",
    billing_address: dict | None = None,
    shipping_address: dict | None = None,
    notes: str = "",
    shipping_rate_id: int | None = None,
    discount_code: str = "",
) -> Order:
    cart = recalculate_cart(cart)
    if not cart.items.exists():
        raise ValueError("Cart is empty.")

    cart_items = list(cart.items.select_related("product_variant", "product_variant__product").all())
    for item in cart_items:
        ensure_variant_inventory(item.product_variant, item.quantity)

    pricing = calculate_cart_pricing(
        cart,
        shipping_address=shipping_address or {},
        shipping_rate_id=shipping_rate_id,
        discount_code=discount_code,
    )
    discount = pricing.pop("discount_code_obj", None)

    order = Order.objects.create(
        site=cart.site,
        order_number=build_order_number(),
        status=Order.STATUS_PENDING,
        payment_status=Order.PAYMENT_PENDING,
        currency=cart.currency,
        customer_name=customer_name,
        customer_email=customer_email,
        customer_phone=customer_phone,
        billing_address=billing_address or {},
        shipping_address=shipping_address or {},
        notes=notes,
        subtotal=pricing["subtotal"],
        shipping_total=pricing["shipping_total"],
        tax_total=pricing["tax_total"],
        discount_total=pricing["discount_total"],
        total=pricing["total"],
        pricing_details=pricing["pricing_details"],
    )

    for item in cart_items:
        variant = item.product_variant
        OrderItem.objects.create(
            order=order,
            product=variant.product,
            product_variant=variant,
            title=variant.product.title if variant.is_default else f"{variant.product.title} / {variant.title}",
            sku=variant.sku,
            quantity=item.quantity,
            unit_price=item.unit_price,
            line_total=item.line_total,
            attributes=variant.attributes or {},
        )

        if variant.track_inventory:
            variant.inventory = max(0, variant.inventory - item.quantity)
            variant.save(update_fields=["inventory", "updated_at"])

    cart.status = Cart.STATUS_CONVERTED
    cart.converted_at = timezone.now()
    cart.save(update_fields=["status", "converted_at", "updated_at"])
    if discount:
        discount.use_count += 1
        discount.save(update_fields=["use_count"])
    return order


def starter_kits() -> list[dict]:
    return [
        {
            "slug": "agency",
            "name": "Agency System",
            "summary": "Lead-gen and services structure with proof, offers, and contact flow.",
            "pages": ["Home", "Services", "Contact"],
        },
        {
            "slug": "commerce",
            "name": "Commerce Launchpad",
            "summary": "Product storytelling with catalog, offer stack, and support page foundations.",
            "pages": ["Home", "Catalog", "Support"],
        },
        {
            "slug": "creator",
            "name": "Creator Studio",
            "summary": "Portfolio, newsletter, speaking, and booking presence for personal brands.",
            "pages": ["Home", "About", "Book"],
        },
    ]


def _hero_markup(
    eyebrow: str,
    heading: str,
    body: str,
    primary: str,
    secondary: str,
    metrics: Iterable[tuple[str, str]],
) -> str:
    metric_markup = "".join(
        f'<div class="wb-metric"><strong>{value}</strong><span>{label}</span></div>' for value, label in metrics
    )
    return f"""
    <section class="wb-hero">
      <div class="wb-shell">
        <div class="wb-hero-panel wb-stack">
          <div class="wb-eyebrow">{eyebrow}</div>
          <h1>{heading}</h1>
          <p>{body}</p>
          <div class="wb-actions">
            <a class="wb-button wb-button-primary" href="#next">{primary}</a>
            <a class="wb-button wb-button-secondary" href="#contact">{secondary}</a>
          </div>
          <div class="wb-grid wb-grid-3">{metric_markup}</div>
        </div>
      </div>
    </section>
    """.strip()


def _agency_home() -> tuple[str, str]:
    html = (
        _hero_markup(
            "Strategy. Design. Growth.",
            "Build the website your business team actually needs.",
            "Run campaigns, launch pages, publish content, and ship changes without waiting on a rebuild every week.",
            "Start the build",
            "Talk to sales",
            [("14d", "average launch cycle"), ("42%", "higher conversion lift"), ("24/7", "marketing control")],
        )
        + """
        <section class="wb-section" id="next">
          <div class="wb-shell wb-grid wb-grid-3">
            <div class="wb-card wb-stack">
              <span class="wb-badge">Performance</span>
              <h3>Landing pages, content hubs, and funnels</h3>
              <p>Move from one page to a complete publishing machine with reusable patterns and fast page cloning.</p>
            </div>
            <div class="wb-card wb-stack">
              <span class="wb-badge">Operations</span>
              <h3>Editing for teams, not just developers</h3>
              <p>Designers tune layouts, marketers update copy, and stakeholders preview changes before publish.</p>
            </div>
            <div class="wb-card wb-stack">
              <span class="wb-badge">Scale</span>
              <h3>One system for every growth sprint</h3>
              <p>Expand from launch site to resource center, services pages, campaign pages, and conversion experiments.</p>
            </div>
          </div>
        </section>
        <section class="wb-section">
          <div class="wb-shell wb-grid wb-grid-2">
            <div class="wb-stack">
              <h2>What your website should do after the redesign is over.</h2>
              <p>Ship proof-driven pages, flexible service detail sections, and conversion-oriented CTAs that can evolve every quarter.</p>
            </div>
            <div class="wb-card wb-stack">
              <h3>Core outcomes</h3>
              <ul class="wb-list">
                <li>Modular page building for campaigns and service launches</li>
                <li>SEO-ready content pages with page-level metadata</li>
                <li>Drafts, revisions, and publish workflows without plugin sprawl</li>
              </ul>
            </div>
          </div>
        </section>
        <section class="wb-section wb-center" id="contact">
          <div class="wb-shell wb-surface" style="padding: 40px;">
            <h2>Ready to launch a serious website system?</h2>
            <p>Use this starter as the basis for agency, SaaS, consulting, or local business sites.</p>
          </div>
        </section>
        <footer class="wb-footer">
          <div class="wb-shell">Powered by the Website Builder starter system.</div>
        </footer>
        """
    )
    return html.strip(), ""


def _agency_services() -> tuple[str, str]:
    html = """
    <section class="wb-section">
      <div class="wb-shell wb-stack">
        <span class="wb-badge">Services</span>
        <h2>Systems for websites that need to convert, rank, and evolve.</h2>
        <div class="wb-grid wb-grid-3">
          <div class="wb-card wb-stack">
            <h3>Conversion Architecture</h3>
            <p>Message hierarchy, CTA strategy, and funnel page design.</p>
          </div>
          <div class="wb-card wb-stack">
            <h3>Content Systems</h3>
            <p>Scalable landing page, blog, and resource center structures.</p>
          </div>
          <div class="wb-card wb-stack">
            <h3>Growth Operations</h3>
            <p>Reusable blocks so your team can launch faster without breaking design consistency.</p>
          </div>
        </div>
      </div>
    </section>
    """.strip()
    return html, ""


def _agency_contact() -> tuple[str, str]:
    html = """
    <section class="wb-section">
      <div class="wb-shell wb-grid wb-grid-2">
        <div class="wb-stack">
          <span class="wb-badge">Contact</span>
          <h2>Talk through your next website launch.</h2>
          <p>Share your offer, audience, and growth goals. Use this page as a base for forms, booking, or sales intake.</p>
        </div>
        <div class="wb-card wb-stack">
          <h3>What to include</h3>
          <ul class="wb-list">
            <li>Revenue model and target audience</li>
            <li>Current bottlenecks in your site workflow</li>
            <li>Desired launch timeline</li>
          </ul>
        </div>
      </div>
    </section>
    """.strip()
    return html, ""


def _commerce_home() -> tuple[str, str]:
    html = (
        _hero_markup(
            "Commerce systems",
            "Sell with pages that feel premium from the first scroll.",
            "Launch hero stories, product sections, social proof, bundles, and support content from one visual editing system.",
            "Shop the collection",
            "Need help?",
            [("3.8x", "average AOV with bundles"), ("1 system", "for product and content"), ("0 code", "for daily edits")],
        )
        + """
        <section class="wb-section">
          <div class="wb-shell wb-grid wb-grid-3">
            <div class="wb-card wb-stack">
              <h3>Story-led product blocks</h3>
              <p>Mix editorial layouts, feature callouts, and offer stacks.</p>
            </div>
            <div class="wb-card wb-stack">
              <h3>Catalog pages</h3>
              <p>Use this starter for collections, seasonal drops, and featured products.</p>
            </div>
            <div class="wb-card wb-stack">
              <h3>Post-purchase content</h3>
              <p>Support, education, and FAQ pages live in the same CMS.</p>
            </div>
          </div>
        </section>
        """
    )
    return html.strip(), ""


def _commerce_catalog() -> tuple[str, str]:
    html = """
    <section class="wb-section">
      <div class="wb-shell wb-stack">
        <span class="wb-badge">Catalog</span>
        <h2>Featured products</h2>
        <div class="wb-grid wb-grid-3">
          <div class="wb-card wb-stack">
            <h3>Signature Pack</h3>
            <div class="wb-price">$149</div>
            <p>Premium starter offer with room for custom upsells and bundle messaging.</p>
          </div>
          <div class="wb-card wb-stack">
            <h3>Launch Bundle</h3>
            <div class="wb-price">$289</div>
            <p>Use for hero SKUs, bundle logic, or lead product offers.</p>
          </div>
          <div class="wb-card wb-stack">
            <h3>Annual Membership</h3>
            <div class="wb-price">$39/mo</div>
            <p>Ideal for memberships, subscriptions, and recurring content products.</p>
          </div>
        </div>
      </div>
    </section>
    """.strip()
    return html, ""


def _commerce_support() -> tuple[str, str]:
    html = """
    <section class="wb-section">
      <div class="wb-shell wb-grid wb-grid-2">
        <div class="wb-stack">
          <span class="wb-badge">Support</span>
          <h2>Help customers before tickets happen.</h2>
          <p>Turn this into shipping, returns, product education, or account management content.</p>
        </div>
        <div class="wb-card wb-stack">
          <ul class="wb-list">
            <li>Shipping and fulfillment expectations</li>
            <li>Returns and guarantees</li>
            <li>Product care and onboarding</li>
          </ul>
        </div>
      </div>
    </section>
    """.strip()
    return html, ""


def _creator_home() -> tuple[str, str]:
    html = (
        _hero_markup(
            "Creator platform",
            "Turn your personal brand into a complete publishing business.",
            "Show your work, collect leads, sell expertise, and route inbound opportunities through a site you control.",
            "View the work",
            "Book a call",
            [("120k+", "monthly readers"), ("4 offers", "in one stack"), ("1 inbox", "for leads and media")],
        )
        + """
        <section class="wb-section">
          <div class="wb-shell wb-grid wb-grid-2">
            <div class="wb-card wb-stack">
              <h3>Newsletter and audience capture</h3>
              <p>Use opt-in sections, proof modules, and premium content teasers.</p>
            </div>
            <div class="wb-card wb-stack">
              <h3>Speaking, consulting, and brand partnerships</h3>
              <p>Package services and authority proof without breaking the editorial feel of the site.</p>
            </div>
          </div>
        </section>
        """
    )
    return html.strip(), ""


def _creator_about() -> tuple[str, str]:
    html = """
    <section class="wb-section">
      <div class="wb-shell wb-grid wb-grid-2">
        <div class="wb-stack">
          <span class="wb-badge">About</span>
          <h2>Frame the story behind the brand.</h2>
          <p>Use this page for personal narrative, credentials, milestones, and platform authority.</p>
        </div>
        <div class="wb-card wb-stack">
          <ul class="wb-list">
            <li>Bio and positioning</li>
            <li>Selected clients or media features</li>
            <li>Signature frameworks or philosophy</li>
          </ul>
        </div>
      </div>
    </section>
    """.strip()
    return html, ""


def _creator_book() -> tuple[str, str]:
    html = """
    <section class="wb-section">
      <div class="wb-shell wb-center wb-stack">
        <span class="wb-badge">Bookings</span>
        <h2>Invite the right work in.</h2>
        <p>Use this for consulting, workshops, speaking, podcasts, or partnerships.</p>
        <div class="wb-actions" style="justify-content: center;">
          <a class="wb-button wb-button-primary" href="mailto:hello@example.com">Request availability</a>
        </div>
      </div>
    </section>
    """.strip()
    return html, ""


STARTER_PAGE_MAP = {
    "agency": [
        ("Home", "home", True, _agency_home),
        ("Services", "services", False, _agency_services),
        ("Contact", "contact", False, _agency_contact),
    ],
    "commerce": [
        ("Home", "home", True, _commerce_home),
        ("Catalog", "catalog", False, _commerce_catalog),
        ("Support", "support", False, _commerce_support),
    ],
    "creator": [
        ("Home", "home", True, _creator_home),
        ("About", "about", False, _creator_about),
        ("Book", "book", False, _creator_book),
    ],
}


def create_site_starter_content(site: Site, starter_kit: str) -> None:
    template = STARTER_PAGE_MAP.get(starter_kit) or STARTER_PAGE_MAP["agency"]
    site.settings = {**site.settings, "starter_kit": starter_kit}
    site.navigation = [{"label": title, "slug": slug, "homepage": is_homepage} for title, slug, is_homepage, _ in template]
    site.save(update_fields=["settings", "navigation"])

    for title, slug, is_homepage, factory in template:
        html, css = factory()
        seo_payload = {
            "meta_title": f"{site.name} | {title}",
            "meta_description": site.tagline or site.description or f"{title} page for {site.name}",
        }
        normalized = normalize_page_content(
            title=title,
            slug=slug,
            path=normalize_page_path(slug, is_homepage),
            is_homepage=is_homepage,
            status=Page.STATUS_DRAFT,
            locale_code="",
            builder_data={},
            seo=seo_payload,
            page_settings={},
            html=html,
            css=css,
            js="",
            strict=True,
        )
        Page.objects.create(
            site=site,
            title=title,
            slug=slug,
            path=normalized["path"],
            status=Page.STATUS_DRAFT,
            is_homepage=is_homepage,
            seo=normalized["seo"],
            page_settings=normalized["page_settings"],
            builder_schema_version=normalized["schema_version"],
            builder_data=normalized["builder_data"],
            html=normalized["html"],
            css=normalized["css"],
            js=normalized["js"],
        )


def ensure_site_cms_modules(site: Site) -> None:
    if not site.post_categories.filter(slug="editorial").exists():
        editorial = PostCategory.objects.create(
            site=site,
            name="Editorial",
            slug="editorial",
            description="Long-form posts, guides, and thought leadership.",
        )
    else:
        editorial = site.post_categories.get(slug="editorial")

    if not site.post_tags.filter(slug="launch").exists():
        launch = PostTag.objects.create(site=site, name="Launch", slug="launch")
    else:
        launch = site.post_tags.get(slug="launch")

    if not site.post_tags.filter(slug="builder").exists():
        stack = PostTag.objects.create(site=site, name="Builder", slug="builder")
    else:
        stack = site.post_tags.get(slug="builder")

    if not site.posts.filter(slug="run-your-site-like-a-publishing-system").exists():
        post = Post.objects.create(
            site=site,
            title="How to run your site like a publishing system",
            slug="run-your-site-like-a-publishing-system",
            excerpt="A starter article showing how posts, pages, and offers can live in the same website operating system.",
            body_html="""
            <section class="wb-section">
              <div class="wb-shell wb-grid wb-grid-2">
                <div class="wb-stack">
                  <span class="wb-badge">Editorial</span>
                  <h1>How to run your site like a publishing system</h1>
                  <p>Use posts for articles, guides, release notes, case studies, and SEO content while keeping your core pages conversion-focused.</p>
                </div>
                <div class="wb-card wb-stack">
                  <h3>What this unlocks</h3>
                  <ul class="wb-list">
                    <li>Posts for topical publishing and search growth</li>
                    <li>Pages for offers, campaigns, and landing flows</li>
                    <li>One shared design language across both</li>
                  </ul>
                </div>
              </div>
            </section>
            <section class="wb-section">
              <div class="wb-shell wb-stack">
                <h2>Why this matters</h2>
                <p>Most teams break their website into too many disconnected tools. A stronger setup keeps brand, publishing, lead capture, and campaign pages in one system.</p>
                <p>This project now includes post taxonomies, comments, media assets, and form submissions so the builder can grow beyond simple pages.</p>
              </div>
            </section>
            """.strip(),
            status=Post.STATUS_PUBLISHED,
            published_at=timezone.now(),
            seo={
                "meta_title": f"{site.name} | Publishing system guide",
                "meta_description": site.tagline or site.description,
            },
        )
        post.categories.add(editorial)
        post.tags.add(launch, stack)

    if not site.form_submissions.exists():
        FormSubmission.objects.create(
            site=site,
            page=site.pages.filter(is_homepage=True).first(),
            form_name="Homepage demo lead",
            payload={
                "name": "Avery Moore",
                "email": "avery@example.com",
                "message": "Interested in turning this builder into our marketing OS.",
            },
        )


def ensure_site_commerce_modules(site: Site) -> None:
    if not site.product_categories.filter(slug="featured-products").exists():
        category = ProductCategory.objects.create(
            site=site,
            name="Featured Products",
            slug="featured-products",
            description="Core products for the demo storefront.",
        )
    else:
        category = site.product_categories.get(slug="featured-products")

    starter_products = [
        {
            "title": "Launch System Kit",
            "slug": "launch-system-kit",
            "excerpt": "A complete website launch toolkit with templates, growth systems, and operations guidance.",
            "description_html": """
            <section class="wb-section">
              <div class="wb-shell wb-grid wb-grid-2">
                <div class="wb-stack">
                  <span class="wb-badge">Product</span>
                  <h1>Launch System Kit</h1>
                  <p>Use this flagship offer to sell templates, implementation packs, or productized service bundles.</p>
                </div>
                <div class="wb-card wb-stack">
                  <h3>Included</h3>
                  <ul class="wb-list">
                    <li>Page templates and launch checklist</li>
                    <li>Offer structure and messaging guidance</li>
                    <li>Operations notes for future campaigns</li>
                  </ul>
                </div>
              </div>
            </section>
            """.strip(),
            "variants": [
                {
                    "title": "Digital Access",
                    "sku": "LSK-DIGITAL",
                    "price": "149.00",
                    "compare_at_price": "199.00",
                    "inventory": 999,
                    "track_inventory": False,
                    "is_default": True,
                    "attributes": {"delivery": "digital"},
                },
                {
                    "title": "Digital + Advisory",
                    "sku": "LSK-ADVISORY",
                    "price": "349.00",
                    "compare_at_price": "449.00",
                    "inventory": 25,
                    "track_inventory": True,
                    "is_default": False,
                    "attributes": {"delivery": "hybrid"},
                },
            ],
        },
        {
            "title": "Growth Sprint Workshop",
            "slug": "growth-sprint-workshop",
            "excerpt": "A short, high-leverage workshop product for teams improving messaging, offers, and landing pages.",
            "description_html": """
            <section class="wb-section">
              <div class="wb-shell wb-grid wb-grid-2">
                <div class="wb-stack">
                  <span class="wb-badge">Workshop</span>
                  <h1>Growth Sprint Workshop</h1>
                  <p>Position services or workshop products inside the same platform as your content and conversion pages.</p>
                </div>
                <div class="wb-card wb-stack">
                  <h3>Perfect for</h3>
                  <ul class="wb-list">
                    <li>Messaging overhauls</li>
                    <li>Offer repositioning</li>
                    <li>Launch planning and funnel fixes</li>
                  </ul>
                </div>
              </div>
            </section>
            """.strip(),
            "variants": [
                {
                    "title": "Workshop Seat",
                    "sku": "GSW-SEAT",
                    "price": "499.00",
                    "compare_at_price": "649.00",
                    "inventory": 40,
                    "track_inventory": True,
                    "is_default": True,
                    "attributes": {"duration": "90m"},
                }
            ],
        },
    ]

    for product_data in starter_products:
        product, created = site.products.get_or_create(
            slug=product_data["slug"],
            defaults={
                "title": product_data["title"],
                "excerpt": product_data["excerpt"],
                "description_html": product_data["description_html"],
                "status": Product.STATUS_PUBLISHED,
                "is_featured": True,
                "published_at": timezone.now(),
                "seo": {
                    "meta_title": f"{site.name} | {product_data['title']}",
                    "meta_description": product_data["excerpt"],
                },
            },
        )
        if created:
            product.categories.add(category)

        for variant_data in product_data["variants"]:
            product.variants.get_or_create(
                sku=variant_data["sku"],
                defaults={
                    "title": variant_data["title"],
                    "price": quantize_money(variant_data["price"]),
                    "compare_at_price": quantize_money(variant_data["compare_at_price"])
                    if variant_data.get("compare_at_price")
                    else None,
                    "inventory": variant_data["inventory"],
                    "track_inventory": variant_data["track_inventory"],
                    "is_default": variant_data["is_default"],
                    "attributes": variant_data.get("attributes", {}),
                },
            )

    shipping_seed = [
        {
            "name": "United States",
            "countries": ["US"],
            "rates": [
                {"name": "Standard", "method_code": "standard", "price": "7.50", "estimated_days_min": 3, "estimated_days_max": 5},
                {"name": "Express", "method_code": "express", "price": "18.00", "estimated_days_min": 1, "estimated_days_max": 2},
            ],
        },
        {
            "name": "International",
            "countries": ["CA", "GB", "AU", "*"],
            "rates": [
                {"name": "International Standard", "method_code": "intl-standard", "price": "16.00", "estimated_days_min": 6, "estimated_days_max": 10},
                {"name": "International Priority", "method_code": "intl-priority", "price": "32.00", "estimated_days_min": 3, "estimated_days_max": 5},
            ],
        },
    ]

    for zone_data in shipping_seed:
        zone, _ = site.shipping_zones.get_or_create(
            name=zone_data["name"],
            defaults={"countries": zone_data["countries"], "active": True},
        )
        if zone.countries != zone_data["countries"]:
            zone.countries = zone_data["countries"]
            zone.save(update_fields=["countries"])
        for rate_data in zone_data["rates"]:
            zone.rates.get_or_create(
                method_code=rate_data["method_code"],
                defaults={
                    "name": rate_data["name"],
                    "price": quantize_money(rate_data["price"]),
                    "estimated_days_min": rate_data["estimated_days_min"],
                    "estimated_days_max": rate_data["estimated_days_max"],
                    "active": True,
                },
            )

    tax_seed = [
        {"name": "US Sales Tax", "rate": Decimal("0.0825"), "countries": ["US"], "states": []},
        {"name": "UK VAT", "rate": Decimal("0.20"), "countries": ["GB"], "states": []},
    ]
    for tax_data in tax_seed:
        site.tax_rates.get_or_create(
            name=tax_data["name"],
            defaults={
                "rate": tax_data["rate"],
                "countries": tax_data["countries"],
                "states": tax_data["states"],
                "active": True,
            },
        )

    discount_seed = [
        {
            "code": "SAVE10",
            "discount_type": DiscountCode.TYPE_PERCENTAGE,
            "value": Decimal("10.00"),
            "min_purchase": Decimal("0.00"),
        },
        {
            "code": "FREESHIP",
            "discount_type": DiscountCode.TYPE_FREE_SHIPPING,
            "value": Decimal("0.00"),
            "min_purchase": Decimal("75.00"),
        },
    ]
    for discount_data in discount_seed:
        site.discount_codes.get_or_create(
            code=discount_data["code"],
            defaults={
                "discount_type": discount_data["discount_type"],
                "value": discount_data["value"],
                "min_purchase": discount_data["min_purchase"],
                "active": True,
            },
        )


_seed_data_initialised = False


def ensure_seed_data() -> None:
    global _seed_data_initialised
    if not getattr(settings, "ENABLE_REQUEST_SEED_DATA", False):
        return
    if _seed_data_initialised and Site.objects.exists() and BlockTemplate.objects.filter(is_global=True).exists():
        return

    if Site.objects.exists():
        for site in Site.objects.all():
            ensure_site_cms_modules(site)
            ensure_site_commerce_modules(site)
        ensure_global_block_templates()
        _seed_data_initialised = True
        return

    site = Site.objects.create(
        name="Northstar Studio",
        slug="northstar-studio",
        tagline="WordPress-style control for websites that need to ship fast.",
        description="A starter multi-page website builder project.",
        theme=default_theme(),
        settings={"starter_kit": "agency"},
    )
    create_site_starter_content(site, "agency")
    ensure_site_cms_modules(site)
    ensure_site_commerce_modules(site)
    ensure_global_block_templates()

    homepage = site.pages.filter(is_homepage=True).first()
    if homepage:
        homepage.status = Page.STATUS_PUBLISHED
        homepage.published_at = timezone.now()
        homepage.save(update_fields=["status", "published_at"])
        create_revision(homepage, "Initial published demo")
    _seed_data_initialised = True


def ensure_global_block_templates() -> None:
    from .models import BlockTemplate

    templates = [
        {
            "name": "Hero Section - Agency",
            "category": BlockTemplate.CATEGORY_HERO,
            "description": "Premium hero section with eyebrow, heading, body, dual CTAs, and metrics grid.",
            "html": _hero_markup(
                "Strategy. Design. Growth.",
                "Build the website your business team actually needs.",
                "Run campaigns, launch pages, publish content, and ship changes without waiting on a rebuild every week.",
                "Start the build",
                "Talk to sales",
                [("14d", "average launch cycle"), ("42%", "higher conversion lift"), ("24/7", "marketing control")],
            ),
        },
        {
            "name": "Feature Grid - 3 Column",
            "category": BlockTemplate.CATEGORY_FEATURE,
            "description": "Three-column feature grid with badge, heading, and description per card.",
            "html": """
            <section class="wb-section">
              <div class="wb-shell wb-grid wb-grid-3">
                <div class="wb-card wb-stack">
                  <span class="wb-badge">Performance</span>
                  <h3>Landing pages, content hubs, and funnels</h3>
                  <p>Move from one page to a complete publishing machine with reusable patterns and fast page cloning.</p>
                </div>
                <div class="wb-card wb-stack">
                  <span class="wb-badge">Operations</span>
                  <h3>Editing for teams, not just developers</h3>
                  <p>Designers tune layouts, marketers update copy, and stakeholders preview changes before publish.</p>
                </div>
                <div class="wb-card wb-stack">
                  <span class="wb-badge">Scale</span>
                  <h3>One system for every growth sprint</h3>
                  <p>Expand from launch site to resource center, services pages, campaign pages, and conversion experiments.</p>
                </div>
              </div>
            </section>
            """.strip(),
        },
        {
            "name": "CTA Section - Centered",
            "category": BlockTemplate.CATEGORY_CTA,
            "description": "Centered call-to-action section with heading, body, and primary button.",
            "html": """
            <section class="wb-section wb-center">
              <div class="wb-shell wb-surface" style="padding: 40px;">
                <h2>Ready to launch a serious website system?</h2>
                <p>Use this starter as the basis for agency, SaaS, consulting, or local business sites.</p>
                <div class="wb-actions" style="justify-content: center;">
                  <a class="wb-button wb-button-primary" href="#start">Get started</a>
                </div>
              </div>
            </section>
            """.strip(),
        },
        {
            "name": "Content Grid - 2 Column",
            "category": BlockTemplate.CATEGORY_CONTENT,
            "description": "Two-column content layout with heading on left and card on right.",
            "html": """
            <section class="wb-section">
              <div class="wb-shell wb-grid wb-grid-2">
                <div class="wb-stack">
                  <h2>What your website should do after the redesign is over.</h2>
                  <p>Ship proof-driven pages, flexible service detail sections, and conversion-oriented CTAs that can evolve every quarter.</p>
                </div>
                <div class="wb-card wb-stack">
                  <h3>Core outcomes</h3>
                  <ul class="wb-list">
                    <li>Modular page building for campaigns and service launches</li>
                    <li>SEO-ready content pages with page-level metadata</li>
                    <li>Drafts, revisions, and publish workflows without plugin sprawl</li>
                  </ul>
                </div>
              </div>
            </section>
            """.strip(),
        },
        {
            "name": "Pricing Cards - 3 Column",
            "category": BlockTemplate.CATEGORY_PRICING,
            "description": "Three-column pricing grid with product name, price, and description.",
            "html": """
            <section class="wb-section">
              <div class="wb-shell wb-stack">
                <span class="wb-badge">Pricing</span>
                <h2>Choose your plan</h2>
                <div class="wb-grid wb-grid-3">
                  <div class="wb-card wb-stack">
                    <h3>Starter</h3>
                    <div class="wb-price">$49</div>
                    <p>Perfect for small projects and personal sites.</p>
                    <a class="wb-button wb-button-primary" href="#buy">Get started</a>
                  </div>
                  <div class="wb-card wb-stack">
                    <h3>Professional</h3>
                    <div class="wb-price">$149</div>
                    <p>For growing businesses and marketing teams.</p>
                    <a class="wb-button wb-button-primary" href="#buy">Get started</a>
                  </div>
                  <div class="wb-card wb-stack">
                    <h3>Enterprise</h3>
                    <div class="wb-price">$499</div>
                    <p>Advanced features for large organizations.</p>
                    <a class="wb-button wb-button-primary" href="#buy">Contact sales</a>
                  </div>
                </div>
              </div>
            </section>
            """.strip(),
        },
        {
            "name": "Footer - Simple",
            "category": BlockTemplate.CATEGORY_FOOTER,
            "description": "Simple footer with centered text.",
            "html": """
            <footer class="wb-footer">
              <div class="wb-shell wb-center">
                <p>&copy; 2024 Your Company. All rights reserved.</p>
              </div>
            </footer>
            """.strip(),
        },
        {
            "name": "Testimonials - 3 Column",
            "category": BlockTemplate.CATEGORY_TESTIMONIAL,
            "description": "Three testimonial cards with star ratings, quotes, and reviewer names.",
            "html": """
            <section class="wb-section">
              <div class="wb-shell">
                <div class="wb-center wb-stack" style="margin-bottom:48px;">
                  <span class="wb-eyebrow">Social proof</span>
                  <h2 style="font-family:var(--wb-heading-font);font-size:clamp(2rem,4vw,3rem);color:#081120;margin:0;">What our customers say</h2>
                </div>
                <div class="wb-grid wb-grid-3">
                  <div class="wb-card wb-stack">
                    <div style="display:flex;gap:2px;color:var(--wb-brand);">&#9733;&#9733;&#9733;&#9733;&#9733;</div>
                    <p style="font-style:italic;">"This platform completely transformed how we build landing pages. We ship 3x faster with better results."</p>
                    <div style="display:flex;align-items:center;gap:12px;border-top:1px solid rgba(8,17,32,.08);padding-top:14px;">
                      <div style="width:40px;height:40px;border-radius:50%;background:var(--wb-brand);display:flex;align-items:center;justify-content:center;color:#fff;font-weight:700;">S</div>
                      <div><strong style="display:block;font-size:.9rem;">Sarah K.</strong><span style="font-size:.8rem;color:#64748b;">Head of Marketing</span></div>
                    </div>
                  </div>
                  <div class="wb-card wb-stack">
                    <div style="display:flex;gap:2px;color:var(--wb-brand);">&#9733;&#9733;&#9733;&#9733;&#9733;</div>
                    <p style="font-style:italic;">"The drag-and-drop builder is incredibly intuitive. Our non-technical team can now own the website."</p>
                    <div style="display:flex;align-items:center;gap:12px;border-top:1px solid rgba(8,17,32,.08);padding-top:14px;">
                      <div style="width:40px;height:40px;border-radius:50%;background:var(--wb-accent);display:flex;align-items:center;justify-content:center;color:#fff;font-weight:700;">M</div>
                      <div><strong style="display:block;font-size:.9rem;">Marcus T.</strong><span style="font-size:.8rem;color:#64748b;">Founder, Studio Nord</span></div>
                    </div>
                  </div>
                  <div class="wb-card wb-stack">
                    <div style="display:flex;gap:2px;color:var(--wb-brand);">&#9733;&#9733;&#9733;&#9733;&#9733;</div>
                    <p style="font-style:italic;">"Customer support is outstanding and the template library saved us weeks of design work."</p>
                    <div style="display:flex;align-items:center;gap:12px;border-top:1px solid rgba(8,17,32,.08);padding-top:14px;">
                      <div style="width:40px;height:40px;border-radius:50%;background:#8b5cf6;display:flex;align-items:center;justify-content:center;color:#fff;font-weight:700;">J</div>
                      <div><strong style="display:block;font-size:.9rem;">Jenna R.</strong><span style="font-size:.8rem;color:#64748b;">Designer, Pixel Works</span></div>
                    </div>
                  </div>
                </div>
              </div>
            </section>
            """.strip(),
        },
        {
            "name": "FAQ - Accordion",
            "category": BlockTemplate.CATEGORY_FAQ,
            "description": "Accordion-style FAQ section with four questions and answers.",
            "html": """
            <section class="wb-section">
              <div class="wb-shell" style="max-width:720px;margin:0 auto;">
                <div class="wb-center wb-stack" style="margin-bottom:48px;">
                  <span class="wb-eyebrow">FAQ</span>
                  <h2 style="font-family:var(--wb-heading-font);font-size:clamp(2rem,4vw,2.8rem);color:#081120;margin:0;">Frequently asked questions</h2>
                </div>
                <div class="wb-stack" style="gap:0;">
                  <details style="border-top:1px solid rgba(8,17,32,.1);padding:18px 0;" open>
                    <summary style="cursor:pointer;font-weight:600;color:#081120;list-style:none;display:flex;justify-content:space-between;align-items:center;">How do I get started? <span style="color:var(--wb-brand);">+</span></summary>
                    <p style="margin-top:12px;color:rgba(8,17,32,.72);">Sign up for a free account, pick a template, and begin customising in the visual builder immediately. No coding required.</p>
                  </details>
                  <details style="border-top:1px solid rgba(8,17,32,.1);padding:18px 0;">
                    <summary style="cursor:pointer;font-weight:600;color:#081120;list-style:none;display:flex;justify-content:space-between;align-items:center;">Can I use a custom domain? <span style="color:var(--wb-brand);">+</span></summary>
                    <p style="margin-top:12px;color:rgba(8,17,32,.72);">Yes — connect any domain you own via the Domains panel in your site settings. DNS verification is guided step by step.</p>
                  </details>
                  <details style="border-top:1px solid rgba(8,17,32,.1);padding:18px 0;">
                    <summary style="cursor:pointer;font-weight:600;color:#081120;list-style:none;display:flex;justify-content:space-between;align-items:center;">Is there a free plan? <span style="color:var(--wb-brand);">+</span></summary>
                    <p style="margin-top:12px;color:rgba(8,17,32,.72);">The Starter plan is free forever with generous limits. Upgrade to Pro for custom domains and advanced analytics.</p>
                  </details>
                  <details style="border-top:1px solid rgba(8,17,32,.1);border-bottom:1px solid rgba(8,17,32,.1);padding:18px 0;">
                    <summary style="cursor:pointer;font-weight:600;color:#081120;list-style:none;display:flex;justify-content:space-between;align-items:center;">Can I export my site? <span style="color:var(--wb-brand);">+</span></summary>
                    <p style="margin-top:12px;color:rgba(8,17,32,.72);">Export clean HTML, CSS and JS at any time. Your content is always yours.</p>
                  </details>
                </div>
              </div>
            </section>
            """.strip(),
        },
        {
            "name": "Contact Form - Split",
            "category": BlockTemplate.CATEGORY_FORM,
            "description": "Two-column contact section with details on left and form card on right.",
            "html": """
            <section class="wb-section">
              <div class="wb-shell">
                <div class="wb-grid wb-grid-2" style="gap:64px;align-items:start;">
                  <div class="wb-stack">
                    <span class="wb-eyebrow">Get in touch</span>
                    <h2 style="font-family:var(--wb-heading-font);font-size:clamp(2rem,4vw,3rem);color:#081120;margin:0;">Let's start a conversation</h2>
                    <p>Have a project in mind? Fill in the form and we'll be in touch within 24 hours.</p>
                    <div class="wb-stack" style="gap:8px;">
                      <div style="display:flex;gap:10px;align-items:center;"><span style="color:var(--wb-brand);">&#128231;</span> hello@example.com</div>
                      <div style="display:flex;gap:10px;align-items:center;"><span style="color:var(--wb-brand);">&#128222;</span> +1 (555) 123-4567</div>
                    </div>
                  </div>
                  <div class="wb-card wb-stack">
                    <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;">
                      <div><label style="display:block;font-size:.85rem;font-weight:600;margin-bottom:6px;">First name</label><input type="text" placeholder="Jane" style="width:100%;border:1px solid rgba(8,17,32,.14);border-radius:10px;padding:10px 14px;font-size:.9rem;" /></div>
                      <div><label style="display:block;font-size:.85rem;font-weight:600;margin-bottom:6px;">Last name</label><input type="text" placeholder="Smith" style="width:100%;border:1px solid rgba(8,17,32,.14);border-radius:10px;padding:10px 14px;font-size:.9rem;" /></div>
                    </div>
                    <div><label style="display:block;font-size:.85rem;font-weight:600;margin-bottom:6px;">Email</label><input type="email" placeholder="jane@company.com" style="width:100%;border:1px solid rgba(8,17,32,.14);border-radius:10px;padding:10px 14px;font-size:.9rem;" /></div>
                    <div><label style="display:block;font-size:.85rem;font-weight:600;margin-bottom:6px;">Message</label><textarea rows="4" placeholder="Tell us about your project..." style="width:100%;border:1px solid rgba(8,17,32,.14);border-radius:10px;padding:10px 14px;font-size:.9rem;resize:vertical;"></textarea></div>
                    <button type="submit" class="wb-button wb-button-primary" style="width:100%;justify-content:center;">Send message</button>
                  </div>
                </div>
              </div>
            </section>
            """.strip(),
        },
        {
            "name": "Stats - 3 Metrics",
            "category": BlockTemplate.CATEGORY_CONTENT,
            "description": "Three large metric stats in a horizontal grid with labels.",
            "html": """
            <section class="wb-section" style="background:color-mix(in srgb,var(--wb-brand) 4%,#f8faff 96%);">
              <div class="wb-shell">
                <div class="wb-grid wb-grid-3" style="gap:48px;text-align:center;">
                  <div><strong style="font-size:3.2rem;font-family:var(--wb-heading-font);color:var(--wb-brand);display:block;">12k+</strong><p style="color:rgba(8,17,32,.72);margin:6px 0 0;">Sites created</p></div>
                  <div><strong style="font-size:3.2rem;font-family:var(--wb-heading-font);color:var(--wb-brand);display:block;">98%</strong><p style="color:rgba(8,17,32,.72);margin:6px 0 0;">Satisfaction rate</p></div>
                  <div><strong style="font-size:3.2rem;font-family:var(--wb-heading-font);color:var(--wb-brand);display:block;">3x</strong><p style="color:rgba(8,17,32,.72);margin:6px 0 0;">Faster deployment</p></div>
                </div>
              </div>
            </section>
            """.strip(),
        },
        {
            "name": "Newsletter - Centered",
            "category": BlockTemplate.CATEGORY_OTHER,
            "description": "Centered newsletter signup with email input and subscribe button.",
            "html": """
            <section class="wb-section" style="background:color-mix(in srgb,var(--wb-brand) 5%,#f0f6ff 95%);">
              <div class="wb-shell" style="max-width:620px;margin:0 auto;text-align:center;">
                <div class="wb-stack" style="align-items:center;">
                  <span class="wb-eyebrow">Stay in the loop</span>
                  <h2 style="font-family:var(--wb-heading-font);font-size:clamp(1.8rem,3.5vw,2.8rem);color:#081120;margin:0;">Get the latest updates</h2>
                  <p>Join 5,000+ subscribers. No spam, ever.</p>
                  <form style="display:flex;gap:10px;width:100%;flex-wrap:wrap;justify-content:center;">
                    <input type="email" placeholder="Enter your email" style="flex:1;min-width:200px;border:1px solid rgba(8,17,32,.14);border-radius:999px;padding:12px 20px;font-size:.95rem;" />
                    <button type="submit" class="wb-button wb-button-primary">Subscribe</button>
                  </form>
                </div>
              </div>
            </section>
            """.strip(),
        },
        {
            "name": "Gallery - 6 Image Grid",
            "category": BlockTemplate.CATEGORY_GALLERY,
            "description": "Responsive 6-cell image gallery with placeholder tiles.",
            "html": """
            <section class="wb-section">
              <div class="wb-shell">
                <div class="wb-center" style="margin-bottom:40px;"><h2 style="font-family:var(--wb-heading-font);font-size:clamp(1.8rem,3.5vw,2.8rem);color:#081120;margin:0;">Our Work</h2></div>
                <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:16px;">
                  <div style="border-radius:var(--wb-radius);aspect-ratio:4/3;background:linear-gradient(135deg,color-mix(in srgb,var(--wb-brand) 20%,#eef4ff 80%),#eef4ff);display:flex;align-items:center;justify-content:center;color:var(--wb-brand);font-size:2rem;">&#128444;</div>
                  <div style="border-radius:var(--wb-radius);aspect-ratio:4/3;background:linear-gradient(135deg,color-mix(in srgb,var(--wb-accent) 20%,#f0fdf4 80%),#f0fdf4);display:flex;align-items:center;justify-content:center;color:var(--wb-accent);font-size:2rem;">&#128444;</div>
                  <div style="border-radius:var(--wb-radius);aspect-ratio:4/3;background:linear-gradient(135deg,#f5f3ff,#ddd6fe);display:flex;align-items:center;justify-content:center;color:#8b5cf6;font-size:2rem;">&#128444;</div>
                  <div style="border-radius:var(--wb-radius);aspect-ratio:4/3;background:linear-gradient(135deg,#fffbeb,#fde68a);display:flex;align-items:center;justify-content:center;color:#f59e0b;font-size:2rem;">&#128444;</div>
                  <div style="border-radius:var(--wb-radius);aspect-ratio:4/3;background:linear-gradient(135deg,#fdf2f8,#fbcfe8);display:flex;align-items:center;justify-content:center;color:#ec4899;font-size:2rem;">&#128444;</div>
                  <div style="border-radius:var(--wb-radius);aspect-ratio:4/3;background:linear-gradient(135deg,color-mix(in srgb,var(--wb-brand) 20%,#eef4ff 80%),#eef4ff);display:flex;align-items:center;justify-content:center;color:var(--wb-brand);font-size:2rem;">&#128444;</div>
                </div>
              </div>
            </section>
            """.strip(),
        },
        {
            "name": "Footer - Full with Links",
            "category": BlockTemplate.CATEGORY_FOOTER,
            "description": "Full dark footer with brand, 4 link columns, and copyright bar.",
            "html": """
            <footer style="background:#0f172a;color:rgba(255,255,255,.72);padding:64px 0 32px;">
              <div class="wb-shell">
                <div style="display:grid;grid-template-columns:2fr 1fr 1fr 1fr;gap:40px;margin-bottom:56px;">
                  <div class="wb-stack" style="gap:16px;">
                    <div style="font-family:var(--wb-heading-font);font-size:1.4rem;color:#fff;font-weight:700;">YourBrand</div>
                    <p style="font-size:.9rem;line-height:1.7;max-width:280px;">The visual website builder for teams who care about quality.</p>
                  </div>
                  <div class="wb-stack" style="gap:12px;">
                    <strong style="color:#fff;font-size:.85rem;text-transform:uppercase;letter-spacing:.12em;">Product</strong>
                    <a href="#" style="color:rgba(255,255,255,.6);text-decoration:none;font-size:.9rem;">Features</a>
                    <a href="#" style="color:rgba(255,255,255,.6);text-decoration:none;font-size:.9rem;">Pricing</a>
                    <a href="#" style="color:rgba(255,255,255,.6);text-decoration:none;font-size:.9rem;">Templates</a>
                  </div>
                  <div class="wb-stack" style="gap:12px;">
                    <strong style="color:#fff;font-size:.85rem;text-transform:uppercase;letter-spacing:.12em;">Company</strong>
                    <a href="#" style="color:rgba(255,255,255,.6);text-decoration:none;font-size:.9rem;">About</a>
                    <a href="#" style="color:rgba(255,255,255,.6);text-decoration:none;font-size:.9rem;">Blog</a>
                    <a href="#" style="color:rgba(255,255,255,.6);text-decoration:none;font-size:.9rem;">Careers</a>
                  </div>
                  <div class="wb-stack" style="gap:12px;">
                    <strong style="color:#fff;font-size:.85rem;text-transform:uppercase;letter-spacing:.12em;">Legal</strong>
                    <a href="#" style="color:rgba(255,255,255,.6);text-decoration:none;font-size:.9rem;">Privacy</a>
                    <a href="#" style="color:rgba(255,255,255,.6);text-decoration:none;font-size:.9rem;">Terms</a>
                  </div>
                </div>
                <div style="border-top:1px solid rgba(255,255,255,.08);padding-top:24px;text-align:center;">
                  <p style="font-size:.82rem;color:rgba(255,255,255,.38);">&copy; 2025 YourBrand. All rights reserved.</p>
                </div>
              </div>
            </footer>
            """.strip(),
        },
    ]

    for template_data in templates:
        renderer_key = default_renderer_key_for_block_category(template_data["category"])
        compatibility_flags = {}
        if renderer_key.startswith("forms."):
            compatibility_flags["requires_forms"] = True
        if renderer_key.startswith("blog."):
            compatibility_flags["requires_blog"] = True
        if renderer_key.startswith("commerce."):
            compatibility_flags["requires_commerce"] = True

        builder_payload = normalize_block_template_builder_data(
            {
                "metadata": {
                    "template_name": template_data["name"],
                    "description": template_data["description"],
                }
            },
            renderer_key=renderer_key,
            strict=False,
        )
        BlockTemplate.objects.get_or_create(
            name=template_data["name"],
            is_global=True,
            defaults={
                "category": template_data["category"],
                "renderer_key": renderer_key,
                "default_props_schema": {},
                "version": 1,
                "compatibility_flags": compatibility_flags,
                "description": template_data["description"],
                "builder_data": builder_payload,
                "html": template_data["html"],
                "is_premium": False,
                "status": BlockTemplate.STATUS_PUBLISHED,
                "plan_required": BlockTemplate.PLAN_FREE,
                "author": "Website Builder",
            },
        )


def _dispatch_webhook(webhook_id: int, payload: dict) -> None:
    """Fire a single webhook synchronously. Intended to run in a daemon thread."""
    import hashlib
    import hmac
    import json
    import logging
    from urllib import request as urllib_request
    from .models import Webhook

    logger = logging.getLogger(__name__)
    try:
        webhook = Webhook.objects.get(pk=webhook_id)
    except Exception:
        return

    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib_request.Request(
            webhook.url,
            data=data,
            headers={"Content-Type": "application/json"},
        )

        if webhook.secret:
            signature = hmac.new(
                webhook.secret.encode("utf-8"),
                data,
                hashlib.sha256,
            ).hexdigest()
            req.add_header("X-Webhook-Signature", f"sha256={signature}")

        with urllib_request.urlopen(req, timeout=10) as response:
            if 200 <= response.status < 300:
                webhook.success_count += 1
                webhook.last_triggered_at = timezone.now()
                webhook.save(update_fields=["success_count", "last_triggered_at", "updated_at"])
            else:
                logger.warning("Webhook %s returned status %s", webhook.url, response.status)
                webhook.failure_count += 1
                webhook.save(update_fields=["failure_count", "updated_at"])
    except Exception as exc:
        logger.warning("Webhook %s dispatch failed: %s", getattr(webhook, "url", webhook_id), exc)
        try:
            webhook.failure_count += 1
            webhook.save(update_fields=["failure_count", "updated_at"])
        except Exception:
            pass


def trigger_webhooks(site, event: str, payload: dict) -> None:
    """Enqueue active webhooks for *event* on *site*. Each fires in a daemon thread."""
    import threading
    from .models import Webhook

    compatible_events = {event}
    legacy_alias = {
        "order.created": "order.placed",
        "order.placed": "order.created",
    }.get(event)
    if legacy_alias:
        compatible_events.add(legacy_alias)

    webhook_ids = list(
        Webhook.objects.filter(site=site, event__in=compatible_events, status=Webhook.STATUS_ACTIVE)
        .values_list("pk", flat=True)
    )
    for wid in webhook_ids:
        t = threading.Thread(target=_dispatch_webhook, args=(wid, payload), daemon=True)
        t.start()
