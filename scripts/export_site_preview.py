#!/usr/bin/env python
"""
Export site pages as static preview files for the Next.js /preview route.

Usage:
    python scripts/export_site_preview.py <site_slug>

This writes files to: ../frontend-next/output/site-mirrors/<site_slug>/
- manifest.json
- one .html file per page
"""
import json
import os
import sys
from pathlib import Path

import django

# Setup Django
BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from builder.models import Site, Page, Product, ProductVariant  # noqa: E402


HTML_SHELL = """<!DOCTYPE html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>{title}</title>
  {meta}
  <style>{css}</style>
</head>
<body>
{body}
<script>{js}</script>
</body>
</html>
"""


def main(site_slug: str) -> int:
    try:
        site = Site.objects.get(slug=site_slug)
    except Site.DoesNotExist:
        print(f"Site '{site_slug}' not found", file=sys.stderr)
        return 1

    out_dir = REPO_ROOT / "frontend-next" / "output" / "site-mirrors" / site_slug
    out_dir.mkdir(parents=True, exist_ok=True)

    entries = []
    pages = Page.objects.filter(site=site, status=Page.STATUS_PUBLISHED).order_by("-is_homepage", "title")
    if not pages.exists():
        print("No published pages found; exporting drafts/home if present")
        pages = Page.objects.filter(site=site).order_by("-is_homepage", "title")

    for page in pages:
        url = page.path or f"/{page.slug}"
        filename = "index.html" if url == "/" else f"{page.slug}.html"
        file_path = out_dir / filename

        seo = page.seo or {}
        meta_bits = []
        if seo.get("description"):
            meta_bits.append(f"<meta name=\"description\" content=\"{seo['description']}\" />")
        meta_html = "\n  ".join(meta_bits)

        html = HTML_SHELL.format(
            title=seo.get("title") or page.title,
            meta=meta_html,
            css=page.css or "",
            js=page.js or "",
            body=page.html or "<main><h1>{}</h1></main>".format(page.title),
        )
        file_path.write_text(html, encoding="utf-8")

        entries.append({
            "url": url,
            "file": filename,
            "code": "200",
        })

    # Auto-add a simple shop listing page if products exist and no explicit /shop page exported
    has_shop_page = any(e["url"].rstrip("/") == "/shop" for e in entries)
    products_qs = Product.objects.filter(site=site, status=Product.STATUS_PUBLISHED)
    if not has_shop_page and products_qs.exists():
        items = []
        products = list(products_qs.order_by("title"))
        product_dir = out_dir / "shop"
        product_dir.mkdir(exist_ok=True)

        for prod in products:
            default_variant = ProductVariant.objects.filter(product=prod, is_default=True).first()
            price = default_variant.price if default_variant else None
            price_str = f"${price}" if price is not None else ""
            excerpt = (prod.excerpt or "")[:200]
            items.append({
                "title": prod.title,
                "slug": prod.slug,
                "excerpt": excerpt,
                "price": price_str,
            })

            # Generate product detail page
            product_body = [
                '<main style="max-width: 900px; margin: 40px auto; padding: 0 20px; font-family: system-ui, sans-serif;">',
                f'  <a href="/preview/{site.slug}/shop" style="text-decoration:none;color:#06c">← Back to Shop</a>',
                f'  <h1 style="font-size:2rem;margin:16px 0 12px">{prod.title}</h1>',
                f'  <div style="font-weight:600;color:#0a6;margin-bottom:16px">{price_str}</div>',
                f'  <article style="color:#333;line-height:1.7">{prod.description_html or ""}</article>',
                '</main>',
            ]
            product_html = HTML_SHELL.format(
                title=f"{prod.title} - {site.name}",
                meta="",
                css="",
                js="",
                body="\n".join(product_body),
            )
            (product_dir / f"{prod.slug}.html").write_text(product_html, encoding="utf-8")
            entries.append({"url": f"/shop/{prod.slug}", "file": f"shop/{prod.slug}.html", "code": "200"})

        # Shop listing
        shop_body = [
            '<main style="max-width: 1200px; margin: 40px auto; padding: 0 20px; font-family: system-ui, sans-serif;">',
            '  <h1 style="font-size: 2rem; margin-bottom: 20px;">Shop</h1>',
            '  <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 20px;">',
        ]
        for item in items:
            shop_body.extend([
                '    <article style="border: 1px solid #eee; border-radius: 8px; padding: 16px; background: #fff;">',
                f'      <h2 style="font-size: 1.1rem; margin: 0 0 8px;">{item["title"]}</h2>',
                f'      <p style="color:#666; margin: 0 0 12px;">{item["excerpt"]}</p>',
                f'      <div style="font-weight: 600; color:#0a6; margin-bottom: 12px;">{item["price"]}</div>',
                f'      <a href="/preview/{site.slug}/shop/{item["slug"]}" style="display:inline-block; padding: 8px 12px; background:#0066CC; color:#fff; border-radius:4px; text-decoration:none;">View</a>',
                '    </article>',
            ])
        shop_body.extend(['  </div>', '</main>'])

        shop_html = HTML_SHELL.format(
            title=f"{site.name} - Shop",
            meta="",
            css="",
            js="",
            body="\n".join(shop_body),
        )

        (out_dir / "shop.html").write_text(shop_html, encoding="utf-8")
        entries.append({"url": "/shop", "file": "shop.html", "code": "200"})

    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(entries, indent=2), encoding="utf-8")

    print(f"✓ Exported {len(entries)} pages to {out_dir}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/export_site_preview.py <site_slug>", file=sys.stderr)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
