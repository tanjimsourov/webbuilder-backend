"""
Minimal AI generation service.

OpenAI is optional. When unavailable or unconfigured, deterministic copy and
site-planning suggestions are generated locally so the feature remains usable.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from html import escape
from typing import Any

from django.db import transaction
from django.utils.html import strip_tags
from django.utils.text import slugify

from .app_registry import platform_app_registry
from .models import Page
from .search_services import search_service
from .services import create_revision, ensure_unique_page_path, normalize_page_path, sync_homepage_state

logger = logging.getLogger(__name__)

AI_GOALS = {"page_seo", "hero_copy"}
BLUEPRINT_GOAL = "site_blueprint"
BLUEPRINT_SECTION_KINDS = {
    "hero",
    "logos",
    "feature",
    "stats",
    "testimonial",
    "pricing",
    "faq",
    "cta",
    "contact",
    "gallery",
    "blog",
    "product",
    "content",
    "footer",
}
BLUEPRINT_PAGE_CSS = """
.wb-plan-highlight {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.12);
  color: rgba(255, 255, 255, 0.82);
  font-size: 0.88rem;
}
.wb-plan-mock {
  min-height: 240px;
  border-radius: calc(var(--wb-radius) * 1.1);
  border: 1px solid rgba(8, 17, 32, 0.08);
  background:
    linear-gradient(135deg, color-mix(in srgb, var(--wb-brand) 10%, white 90%), white),
    radial-gradient(circle at top right, rgba(20, 184, 166, 0.12), transparent 44%);
  box-shadow: 0 26px 80px rgba(15, 23, 42, 0.08);
}
.wb-plan-muted {
  color: rgba(8, 17, 32, 0.62);
}
.wb-plan-strip {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 16px;
}
.wb-plan-strip span {
  min-width: 140px;
  padding: 14px 18px;
  border-radius: 999px;
  text-align: center;
  border: 1px solid rgba(8, 17, 32, 0.08);
  background: rgba(255, 255, 255, 0.86);
  font-weight: 700;
  color: rgba(8, 17, 32, 0.72);
}
.wb-plan-footer-grid {
  display: grid;
  gap: 24px;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
}
.wb-plan-footer-grid a {
  text-decoration: none;
  color: rgba(255, 255, 255, 0.7);
}
.wb-plan-faq details {
  border-top: 1px solid rgba(8, 17, 32, 0.08);
  padding: 18px 0;
}
.wb-plan-faq details:last-child {
  border-bottom: 1px solid rgba(8, 17, 32, 0.08);
}
.wb-plan-faq summary {
  cursor: pointer;
  list-style: none;
  font-weight: 700;
  color: #081120;
}
""".strip()


def _compact_text(value: str, limit: int) -> str:
    compact = " ".join(strip_tags(value or "").split())
    if len(compact) <= limit:
        return compact
    return f"{compact[: limit - 1].rstrip(' ,;:-')}..."


def _sentence_case(value: str) -> str:
    cleaned = " ".join((value or "").split()).strip()
    if not cleaned:
        return ""
    return cleaned[0].upper() + cleaned[1:]


def _extract_json_object(value: str) -> dict[str, Any]:
    raw = (value or "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return {}
        try:
            parsed = json.loads(raw[start : end + 1])
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}


def _normalize_keywords(value: Any) -> list[str]:
    if isinstance(value, str):
        raw_items = value.split(",")
    elif isinstance(value, list):
        raw_items = [str(item) for item in value]
    else:
        raw_items = []

    seen: set[str] = set()
    items: list[str] = []
    for item in raw_items:
        cleaned = " ".join(item.strip().split())
        key = cleaned.lower()
        if not cleaned or key in seen:
            continue
        seen.add(key)
        items.append(cleaned)
    return items[:8]


def _safe_id(value: Any, fallback: str) -> str:
    cleaned = slugify(str(value or fallback)).replace("-", "_")
    return cleaned or fallback


def _normalize_section_kind(value: Any) -> str:
    cleaned = slugify(str(value or "")).replace("-", "_")
    mapping = {
        "features": "feature",
        "feature_grid": "feature",
        "testimonials": "testimonial",
        "call_to_action": "cta",
        "faqs": "faq",
        "form": "contact",
        "contact_form": "contact",
        "blog_posts": "blog",
        "products": "product",
        "metrics": "stats",
        "logos_strip": "logos",
    }
    normalized = mapping.get(cleaned, cleaned)
    if normalized in BLUEPRINT_SECTION_KINDS:
        return normalized
    return "content"


def _guess_sections_for_slug(slug: str) -> list[str]:
    slug_lower = (slug or "").lower()
    if slug_lower in {"", "home", "index"}:
        return ["hero", "logos", "feature", "stats", "testimonial", "cta", "footer"]
    if slug_lower in {"about", "about-us", "company"}:
        return ["hero", "content", "stats", "testimonial", "footer"]
    if slug_lower in {"services", "solutions", "product", "platform"}:
        return ["hero", "feature", "content", "testimonial", "cta", "footer"]
    if slug_lower in {"pricing", "plans"}:
        return ["hero", "pricing", "faq", "cta", "footer"]
    if slug_lower in {"contact", "book", "book-demo"}:
        return ["hero", "contact", "faq", "footer"]
    if slug_lower in {"resources", "blog", "journal"}:
        return ["hero", "blog", "cta", "footer"]
    if slug_lower in {"shop", "store", "products"}:
        return ["hero", "product", "testimonial", "faq", "footer"]
    if slug_lower in {"gallery", "work", "portfolio", "case-studies"}:
        return ["hero", "gallery", "testimonial", "cta", "footer"]
    return ["hero", "content", "cta", "footer"]


def _guess_page_purpose(title: str, slug: str, context: dict[str, Any]) -> str:
    slug_lower = (slug or "").lower()
    site_name = context.get("site_name") or "the business"
    offering = context.get("offering") or context.get("site_tagline") or "the offer"
    audience = context.get("audience") or "qualified visitors"

    if slug_lower in {"", "home", "index"}:
        return f"Introduce {site_name}, explain the offer, and convert {audience} into action."
    if slug_lower in {"about", "about-us", "company"}:
        return f"Build trust with the story, positioning, and team behind {site_name}."
    if slug_lower in {"services", "solutions", "product", "platform"}:
        return f"Show how {offering} works, who it helps, and why it wins."
    if slug_lower in {"pricing", "plans"}:
        return "Present packages clearly, handle objections, and guide visitors to the best-fit plan."
    if slug_lower in {"contact", "book", "book-demo"}:
        return "Capture high-intent conversations with a clear next step and response expectation."
    if slug_lower in {"resources", "blog", "journal"}:
        return "Support search demand and nurture prospects with educational content."
    if slug_lower in {"shop", "store", "products"}:
        return "Showcase products clearly and make buying frictionless."
    return f"Support the buyer journey for {audience} and reinforce the value of {site_name}."


def _make_page_spec(
    *,
    page_id: str,
    title: str,
    slug_value: str,
    purpose: str,
    keywords: list[str],
    site_name: str,
    is_homepage: bool = False,
    parent_id: str | None = None,
) -> dict[str, Any]:
    return {
        "id": page_id,
        "title": title,
        "slug": slug_value,
        "path": "/" if is_homepage else normalize_page_path(slug_value, False),
        "purpose": purpose,
        "is_homepage": is_homepage,
        "parent_id": parent_id,
        "sections": [
            {
                "id": _safe_id(f"{page_id}_{section_kind}", f"{page_id}_{index + 1}"),
                "kind": section_kind,
                "title": _sentence_case(section_kind),
                "summary": purpose,
            }
            for index, section_kind in enumerate(_guess_sections_for_slug(slug_value))
        ],
        "seo": {
            "meta_title": _compact_text(f"{title} | {site_name}", 60),
            "meta_description": _compact_text(purpose, 155),
            "focus_keywords": keywords,
        },
    }


def _build_fallback_blueprint_pages(site, context: dict[str, Any]) -> list[dict[str, Any]]:
    signals = " ".join(
        [
            str(context.get("brief", "")),
            str(context.get("offering", "")),
            str(context.get("site_description", "")),
            " ".join(_normalize_keywords(context.get("keywords") or [])),
        ]
    ).lower()
    keywords = _normalize_keywords(context.get("keywords") or [])
    is_store = context.get("has_store") or any(token in signals for token in ("shop", "store", "product", "catalog", "commerce"))
    has_blog = context.get("has_blog") or any(token in signals for token in ("blog", "resource", "content", "seo", "article"))
    existing_pages = context.get("existing_pages") if isinstance(context.get("existing_pages"), list) else []

    specs: list[dict[str, Any]] = []
    seen_paths: set[str] = set()

    for existing in existing_pages[:6]:
        if not isinstance(existing, dict):
            continue
        title = _sentence_case(str(existing.get("title") or "Page"))
        slug_value = slugify(str(existing.get("slug") or title)) or "page"
        purpose = _guess_page_purpose(title, slug_value, context)
        is_homepage = bool(existing.get("is_homepage"))
        path = "/" if is_homepage else normalize_page_path(slug_value, False)
        if path in seen_paths:
            continue
        seen_paths.add(path)
        specs.append(
            _make_page_spec(
                page_id=_safe_id(existing.get("slug") or existing.get("title"), f"page_{len(specs) + 1}"),
                title=title,
                slug_value=slug_value,
                purpose=purpose,
                keywords=keywords,
                site_name=site.name,
                is_homepage=is_homepage,
            )
        )

    essentials: list[tuple[str, str]] = [("Home", "home")]
    if is_store:
        essentials.extend([("Shop", "shop"), ("About", "about"), ("Contact", "contact")])
    else:
        essentials.extend([("Services", "services"), ("About", "about"), ("Pricing", "pricing"), ("Contact", "contact")])
    if has_blog:
        essentials.insert(-1, ("Resources", "resources"))

    for title, slug_value in essentials:
        path = "/" if slug_value == "home" else normalize_page_path(slug_value, False)
        if path in seen_paths:
            continue
        seen_paths.add(path)
        specs.append(
            _make_page_spec(
                page_id=_safe_id(slug_value, slug_value),
                title=title,
                slug_value="home" if slug_value == "home" else slug_value,
                purpose=_guess_page_purpose(title, slug_value, context),
                keywords=keywords,
                site_name=site.name,
                is_homepage=slug_value == "home",
            )
        )

    return specs[:8]


def _normalize_blueprint(site, payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    raw_pages = payload.get("pages") if isinstance(payload.get("pages"), list) else []
    normalized_pages: list[dict[str, Any]] = []

    for index, raw_page in enumerate(raw_pages[:8]):
        if not isinstance(raw_page, dict):
            continue

        title = _sentence_case(str(raw_page.get("title") or raw_page.get("name") or f"Page {index + 1}"))
        slug_value = slugify(str(raw_page.get("slug") or title)) or f"page-{index + 1}"
        purpose = _compact_text(
            str(raw_page.get("purpose") or _guess_page_purpose(title, slug_value, context)),
            220,
        )
        page_id = _safe_id(raw_page.get("id"), f"page_{index + 1}")
        parent_id = _safe_id(raw_page.get("parent_id"), "") if raw_page.get("parent_id") else None
        is_homepage = bool(raw_page.get("is_homepage"))

        raw_sections = raw_page.get("sections") if isinstance(raw_page.get("sections"), list) else []
        if not raw_sections:
            raw_sections = [
                {"kind": section_kind, "title": _sentence_case(section_kind), "summary": purpose}
                for section_kind in _guess_sections_for_slug(slug_value)
            ]

        sections: list[dict[str, Any]] = []
        for section_index, raw_section in enumerate(raw_sections[:7]):
            if not isinstance(raw_section, dict):
                continue
            kind = _normalize_section_kind(raw_section.get("kind"))
            sections.append(
                {
                    "id": _safe_id(raw_section.get("id"), f"{page_id}_{section_index + 1}"),
                    "kind": kind,
                    "title": _sentence_case(str(raw_section.get("title") or kind)),
                    "summary": _compact_text(str(raw_section.get("summary") or purpose), 180),
                }
            )

        raw_seo = raw_page.get("seo") if isinstance(raw_page.get("seo"), dict) else {}
        normalized_pages.append(
            {
                "id": page_id,
                "title": title,
                "slug": slug_value,
                "path": normalize_page_path(slug_value, is_homepage),
                "purpose": purpose,
                "is_homepage": is_homepage,
                "parent_id": parent_id,
                "sections": sections,
                "seo": {
                    "meta_title": _compact_text(str(raw_seo.get("meta_title") or f"{title} | {site.name}"), 60),
                    "meta_description": _compact_text(
                        str(raw_seo.get("meta_description") or purpose or site.description or site.tagline or title),
                        155,
                    ),
                    "focus_keywords": _normalize_keywords(raw_seo.get("focus_keywords") or context.get("keywords") or []),
                },
            }
        )

    if not normalized_pages:
        normalized_pages = _build_fallback_blueprint_pages(site, context)

    homepage_seen = False
    valid_ids = {page["id"] for page in normalized_pages}
    for index, page in enumerate(normalized_pages):
        if page["parent_id"] not in valid_ids or page["parent_id"] == page["id"]:
            page["parent_id"] = None

        if page["is_homepage"] and not homepage_seen:
            homepage_seen = True
            page["path"] = "/"
            continue
        if page["is_homepage"] and homepage_seen:
            page["is_homepage"] = False
        if not homepage_seen and index == 0:
            page["is_homepage"] = True
            page["path"] = "/"
            homepage_seen = True
        elif not page["is_homepage"]:
            page["path"] = normalize_page_path(page["slug"], False)

    return {
        "site_name": _sentence_case(str(payload.get("site_name") or site.name)),
        "site_tagline": _compact_text(str(payload.get("site_tagline") or site.tagline or site.description), 180),
        "positioning": _compact_text(
            str(payload.get("positioning") or context.get("brief") or site.description or site.tagline or ""),
            240,
        ),
        "audience": _compact_text(str(payload.get("audience") or context.get("audience") or ""), 180),
        "offering": _compact_text(str(payload.get("offering") or context.get("offering") or ""), 180),
        "tone": _compact_text(str(payload.get("tone") or context.get("tone") or "clear, premium, conversion-focused"), 80),
        "pages": normalized_pages,
    }


def _card_grid_markup(label: str, heading: str, summary: str, cards: list[tuple[str, str]]) -> str:
    cards_html = "\n".join(
        f'<div class="wb-card wb-stack"><h3>{escape(card_title)}</h3><p>{escape(card_copy)}</p></div>'
        for card_title, card_copy in cards
    )
    return f"""
      <section class="wb-section">
        <div class="wb-shell wb-stack">
          <div class="wb-stack" style="max-width:760px;">
            <span class="wb-eyebrow">{escape(label)}</span>
            <h2>{escape(heading)}</h2>
            <p>{escape(summary)}</p>
          </div>
          <div class="wb-grid wb-grid-3">
            {cards_html}
          </div>
        </div>
      </section>
    """


def _hero_markup(page_plan: dict[str, Any], blueprint: dict[str, Any]) -> str:
    return f"""
      <section class="wb-hero">
        <div class="wb-shell wb-grid wb-grid-2" style="align-items:center; gap:40px;">
          <div class="wb-hero-panel wb-stack">
            <span class="wb-eyebrow">Visual sitemap starter</span>
            <h1>{escape(page_plan["title"])}</h1>
            <p>{escape(page_plan["seo"]["meta_description"] or page_plan["purpose"])}</p>
            <div class="wb-actions">
              <span class="wb-plan-highlight">{escape(blueprint.get("audience") or "Planned with AI")}</span>
              <a class="wb-button wb-button-primary" href="#next">Primary action</a>
              <a class="wb-button wb-button-secondary" href="#contact">Talk to sales</a>
            </div>
          </div>
          <div class="wb-plan-mock wb-card wb-stack">
            <span class="wb-badge">Draft layout</span>
            <h3>{escape(page_plan["purpose"])}</h3>
            <p class="wb-plan-muted">This page was scaffolded from the AI sitemap so the team can refine structure and copy without starting from a blank page.</p>
          </div>
        </div>
      </section>
    """


def _render_section(section: dict[str, Any], page_plan: dict[str, Any], blueprint: dict[str, Any]) -> str:
    kind = section["kind"]
    label = section["title"]
    summary = section["summary"]

    if kind == "hero":
        return _hero_markup(page_plan, blueprint)
    if kind == "logos":
        return """
          <section class="wb-section" style="padding-top:42px; padding-bottom:42px;">
            <div class="wb-shell wb-stack wb-center">
              <span class="wb-eyebrow">Trusted by teams</span>
              <div class="wb-plan-strip">
                <span>Northstar</span>
                <span>Meridian</span>
                <span>Vertex</span>
                <span>Axis</span>
                <span>Summit</span>
              </div>
            </div>
          </section>
        """
    if kind == "feature":
        return _card_grid_markup(
            label,
            "Clear offer framing",
            summary,
            [
                ("Explain the promise", "Use this section to clarify the outcome, method, and differentiators."),
                ("Show why it wins", "Add evidence, process, or product depth without changing the page structure."),
                ("Support conversion", "Keep the copy pointed toward the page's next step or CTA."),
            ],
        )
    if kind == "stats":
        return """
          <section class="wb-section" style="background:color-mix(in srgb,var(--wb-brand) 5%,#f8fbff 95%);">
            <div class="wb-shell wb-grid wb-grid-3" style="text-align:center;">
              <div class="wb-card"><strong class="wb-price">12k+</strong><p>Visitors served</p></div>
              <div class="wb-card"><strong class="wb-price">38%</strong><p>Lead conversion uplift</p></div>
              <div class="wb-card"><strong class="wb-price">3x</strong><p>Faster page launches</p></div>
            </div>
          </section>
        """
    if kind == "testimonial":
        return _card_grid_markup(
            label,
            "Proof that reduces friction",
            summary,
            [
                ("Marketing lead", "\"This structure gave our team a premium starting point immediately.\""),
                ("Operations manager", "\"We moved from scattered planning docs into direct execution in the builder.\""),
                ("Founder", "\"The page hierarchy made site expansion feel deliberate instead of reactive.\""),
            ],
        )
    if kind == "pricing":
        return """
          <section class="wb-section">
            <div class="wb-shell wb-grid wb-grid-3">
              <div class="wb-card wb-stack"><span class="wb-badge">Starter</span><strong class="wb-price">$49</strong><p>Use for entry offers or smaller packages.</p></div>
              <div class="wb-card wb-stack"><span class="wb-badge">Growth</span><strong class="wb-price">$149</strong><p>Position the core offer or most popular plan here.</p></div>
              <div class="wb-card wb-stack"><span class="wb-badge">Scale</span><strong class="wb-price">$399</strong><p>Reserve this for premium retainers or higher-touch services.</p></div>
            </div>
          </section>
        """
    if kind == "faq":
        return f"""
          <section class="wb-section wb-plan-faq">
            <div class="wb-shell wb-stack" style="max-width:820px;">
              <div class="wb-stack">
                <span class="wb-eyebrow">{escape(label)}</span>
                <h2>Questions this page should answer</h2>
                <p>{escape(summary)}</p>
              </div>
              <details open><summary>What belongs here?</summary><p class="wb-plan-muted">Handle objections, logistics, scope, and delivery questions before the visitor needs to ask.</p></details>
              <details><summary>Should this connect to a CTA?</summary><p class="wb-plan-muted">Yes. Pair this section with a booking, checkout, or form action based on the page goal.</p></details>
              <details><summary>Can we customize everything?</summary><p class="wb-plan-muted">This is a structured starter. Replace placeholders with business-specific answers before publishing.</p></details>
            </div>
          </section>
        """
    if kind == "cta":
        return f"""
          <section class="wb-section" style="background:linear-gradient(135deg,var(--wb-brand),color-mix(in srgb,var(--wb-brand) 62%,#081120 38%));">
            <div class="wb-shell wb-center wb-stack">
              <span class="wb-eyebrow" style="color:white;">{escape(label)}</span>
              <h2 style="color:white;">Move the visitor to the next step</h2>
              <p style="color:rgba(255,255,255,.82); max-width:720px; margin:0 auto;">{escape(summary)}</p>
              <div class="wb-actions" style="justify-content:center;">
                <a class="wb-button" style="background:white;color:var(--wb-brand);" href="#contact">Book a call</a>
                <a class="wb-button" style="background:rgba(255,255,255,.12); color:white; border:1px solid rgba(255,255,255,.22);" href="#learn">See how it works</a>
              </div>
            </div>
          </section>
        """
    if kind == "contact":
        return f"""
          <section class="wb-section" id="contact">
            <div class="wb-shell wb-grid wb-grid-2" style="align-items:start;">
              <div class="wb-stack">
                <span class="wb-eyebrow">{escape(label)}</span>
                <h2>Start the conversation</h2>
                <p>{escape(summary)}</p>
                <div class="wb-card wb-stack">
                  <strong>Email</strong>
                  <span class="wb-plan-muted">hello@example.com</span>
                  <strong>Phone</strong>
                  <span class="wb-plan-muted">+1 (555) 123-4567</span>
                </div>
              </div>
              <div class="wb-card wb-stack">
                <div class="wb-grid wb-grid-2">
                  <input type="text" placeholder="First name" style="width:100%; border:1px solid rgba(8,17,32,.14); border-radius:12px; padding:12px 14px;" />
                  <input type="text" placeholder="Last name" style="width:100%; border:1px solid rgba(8,17,32,.14); border-radius:12px; padding:12px 14px;" />
                </div>
                <input type="email" placeholder="Work email" style="width:100%; border:1px solid rgba(8,17,32,.14); border-radius:12px; padding:12px 14px;" />
                <textarea rows="5" placeholder="Tell us what you need" style="width:100%; border:1px solid rgba(8,17,32,.14); border-radius:12px; padding:12px 14px; resize:vertical;"></textarea>
                <button class="wb-button wb-button-primary" style="width:100%; justify-content:center;">Send request</button>
              </div>
            </div>
          </section>
        """
    if kind == "gallery":
        return """
          <section class="wb-section">
            <div class="wb-shell wb-grid wb-grid-3">
              <div class="wb-plan-mock"></div>
              <div class="wb-plan-mock"></div>
              <div class="wb-plan-mock"></div>
            </div>
          </section>
        """
    if kind == "blog":
        return _card_grid_markup(
            label,
            "Content that supports demand generation",
            summary,
            [
                ("Launch guide", "Use this card for an SEO article, insight, or educational story."),
                ("Buyer checklist", "Turn important objections into content that moves visitors forward."),
                ("Proof-driven case study", "Show results and create stronger conversion support for the offer."),
            ],
        )
    if kind == "product":
        return f"""
          <section class="wb-section">
            <div class="wb-shell wb-grid wb-grid-2" style="align-items:center;">
              <div class="wb-plan-mock"></div>
              <div class="wb-stack">
                <span class="wb-eyebrow">{escape(label)}</span>
                <h2>Featured product or collection</h2>
                <p>{escape(summary)}</p>
                <ul class="wb-list">
                  <li>Show the primary benefit first</li>
                  <li>Keep buying actions visible above the fold</li>
                  <li>Use variants or bundles where needed</li>
                </ul>
                <div class="wb-actions">
                  <a class="wb-button wb-button-primary" href="#buy">Buy now</a>
                  <a class="wb-button wb-button-secondary" href="#details">View details</a>
                </div>
              </div>
            </div>
          </section>
        """
    if kind == "footer":
        return """
          <footer class="wb-section" style="background:#081120; color:rgba(255,255,255,.78);">
            <div class="wb-shell wb-stack">
              <div class="wb-plan-footer-grid">
                <div class="wb-stack"><strong style="color:white;">Brand</strong><p style="margin:0; color:rgba(255,255,255,.64);">Premium page scaffolding generated from the AI planner.</p></div>
                <div class="wb-stack"><strong style="color:white;">Product</strong><a href="#">Features</a><a href="#">Pricing</a><a href="#">Templates</a></div>
                <div class="wb-stack"><strong style="color:white;">Company</strong><a href="#">About</a><a href="#">Contact</a><a href="#">Blog</a></div>
                <div class="wb-stack"><strong style="color:white;">Legal</strong><a href="#">Privacy</a><a href="#">Terms</a><a href="#">Cookies</a></div>
              </div>
              <p style="margin:0; color:rgba(255,255,255,.42); font-size:.84rem;">AI site blueprint starter. Customize before publishing.</p>
            </div>
          </footer>
        """
    return _card_grid_markup(
        label,
        label,
        summary,
        [
            ("Narrative block", "Use this area for story, differentiation, process, or supporting detail."),
            ("Trust builder", "Add evidence, screenshots, quotes, or examples that remove friction."),
            ("Action support", "Connect this content to the main CTA and keep the page moving forward."),
        ],
    )


def build_page_markup_from_blueprint(page_plan: dict[str, Any], blueprint: dict[str, Any]) -> tuple[str, str]:
    html = "\n".join(_render_section(section, page_plan, blueprint) for section in (page_plan.get("sections") or []))
    return html.strip(), BLUEPRINT_PAGE_CSS


def _build_navigation_items(blueprint: dict[str, Any], pages_by_plan_id: dict[str, Page]) -> list[dict[str, Any]]:
    page_map = {page_plan["id"]: page_plan for page_plan in blueprint["pages"]}
    children_by_parent: dict[str, list[dict[str, Any]]] = {}
    roots: list[dict[str, Any]] = []

    for page_plan in blueprint["pages"]:
        parent_id = page_plan.get("parent_id")
        if parent_id and parent_id in page_map:
            children_by_parent.setdefault(parent_id, []).append(page_plan)
        else:
            roots.append(page_plan)

    def build_item(page_plan: dict[str, Any]) -> dict[str, Any]:
        page = pages_by_plan_id[page_plan["id"]]
        item = {
            "id": f"nav_{page.id}",
            "label": page.title,
            "url": page.path,
            "target": "_self",
        }
        children = [build_item(child) for child in children_by_parent.get(page_plan["id"], []) if child["id"] in pages_by_plan_id]
        if children:
            item["children"] = children
        return item

    return [build_item(page_plan) for page_plan in roots if page_plan["id"] in pages_by_plan_id]


class AIService:
    def __init__(self):
        self._client = None
        self._openai_import_error = False

    def generate(self, *, goal: str, site, page=None, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if goal not in AI_GOALS:
            raise ValueError(f"Unsupported AI goal: {goal}")

        payload = payload or {}
        context = platform_app_registry.build_ai_context(goal, site, page, payload)
        fallback_suggestion = platform_app_registry.postprocess_ai_output(
            goal,
            site,
            page,
            self._generate_fallback(goal, context),
        )

        provider = "rules"
        model_name = "rules-v1"
        suggestion = fallback_suggestion

        if self._openai_ready():
            try:
                openai_suggestion, model_name = self._generate_openai(goal, context)
                if openai_suggestion:
                    suggestion = platform_app_registry.postprocess_ai_output(goal, site, page, openai_suggestion)
                    provider = "openai"
            except Exception as exc:  # pragma: no cover - network/provider errors
                logger.warning("AI fallback engaged after provider failure: %s", exc)

        return {
            "goal": goal,
            "provider": provider,
            "model": model_name,
            "generated_at": datetime.now(UTC).isoformat(),
            "suggestions": suggestion,
        }

    def generate_site_blueprint(self, *, site, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
        context = platform_app_registry.build_ai_context(BLUEPRINT_GOAL, site, None, payload)
        blueprint = _normalize_blueprint(site, self._generate_blueprint_fallback(site, context), context)

        provider = "rules"
        model_name = "rules-v1"
        if self._openai_ready():
            try:
                openai_blueprint, model_name = self._generate_openai_blueprint(context)
                if openai_blueprint:
                    blueprint = _normalize_blueprint(site, openai_blueprint, context)
                    provider = "openai"
            except Exception as exc:  # pragma: no cover - network/provider errors
                logger.warning("Blueprint fallback engaged after provider failure: %s", exc)

        return {
            "provider": provider,
            "model": model_name,
            "generated_at": datetime.now(UTC).isoformat(),
            "blueprint": blueprint,
        }

    def _openai_ready(self) -> bool:
        if not os.environ.get("OPENAI_API_KEY"):
            return False
        if self._openai_import_error:
            return False
        if self._client is not None:
            return True
        try:
            from openai import OpenAI  # type: ignore
        except ImportError:
            self._openai_import_error = True
            logger.warning("openai package not installed. AI Studio is using fallback mode.")
            return False

        self._client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
        return True

    def _build_input(self, goal: str, context: dict[str, Any]) -> str:
        schema = {
            "title": "Short page title",
            "meta_title": "SEO title under 60 characters",
            "meta_description": "SEO description under 155 characters",
            "hero_heading": "Concise hero headline",
            "hero_subheading": "Short supporting copy",
            "cta_label": "CTA button label under 28 characters",
            "focus_keywords": ["keyword one", "keyword two"],
        }
        return (
            "Create website copy suggestions for the provided context.\n"
            f"Goal: {goal}\n"
            "Return one valid JSON object only. No markdown, no prose.\n"
            "Use the exact keys shown in the schema.\n"
            "Keep results commercial, concrete, and concise.\n\n"
            f"Schema:\n{json.dumps(schema, ensure_ascii=True, indent=2)}\n\n"
            f"Context:\n{json.dumps(context, ensure_ascii=True, indent=2)}\n"
        )

    def _build_blueprint_input(self, context: dict[str, Any]) -> str:
        schema = {
            "site_name": "Brand or site name",
            "site_tagline": "Short positioning line",
            "positioning": "One-sentence strategy note",
            "audience": "Primary audience",
            "offering": "Core offer or product line",
            "tone": "Brand voice",
            "pages": [
                {
                    "id": "home",
                    "title": "Home",
                    "slug": "home",
                    "is_homepage": True,
                    "parent_id": "",
                    "purpose": "What this page should accomplish",
                    "seo": {
                        "meta_title": "SEO title under 60 characters",
                        "meta_description": "SEO description under 155 characters",
                        "focus_keywords": ["keyword one", "keyword two"],
                    },
                    "sections": [
                        {
                            "id": "home_hero",
                            "kind": "hero",
                            "title": "Hero",
                            "summary": "What this section should communicate",
                        }
                    ],
                }
            ],
        }
        return (
            "Create a premium website blueprint for a visual website builder.\n"
            "Return one valid JSON object only. No markdown, no prose.\n"
            "Use the exact schema keys shown below.\n"
            "Create between 4 and 8 pages.\n"
            "Use section kinds from this list only: hero, logos, feature, stats, testimonial, pricing, faq, cta, contact, gallery, blog, product, content, footer.\n"
            "Exactly one page must be the homepage.\n"
            "Keep page purposes and section summaries implementation-ready.\n\n"
            f"Schema:\n{json.dumps(schema, ensure_ascii=True, indent=2)}\n\n"
            f"Context:\n{json.dumps(context, ensure_ascii=True, indent=2)}\n"
        )

    def _generate_openai(self, goal: str, context: dict[str, Any]) -> tuple[dict[str, Any], str]:
        model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
        response = self._client.responses.create(  # type: ignore[union-attr]
            model=model,
            instructions=(
                "You are a senior web copywriter and SEO strategist. "
                "Respond with compact, production-ready copy in JSON only."
            ),
            input=self._build_input(goal, context),
        )
        return _extract_json_object(getattr(response, "output_text", "")), model

    def _generate_openai_blueprint(self, context: dict[str, Any]) -> tuple[dict[str, Any], str]:
        model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
        response = self._client.responses.create(  # type: ignore[union-attr]
            model=model,
            instructions=(
                "You are a principal product strategist and information architect for premium website builders. "
                "Respond with concise, production-ready JSON only."
            ),
            input=self._build_blueprint_input(context),
        )
        return _extract_json_object(getattr(response, "output_text", "")), model

    def _generate_fallback(self, goal: str, context: dict[str, Any]) -> dict[str, Any]:
        site_name = context.get("site_name") or "Your site"
        site_tagline = context.get("site_tagline") or context.get("site_description") or ""
        page_title = context.get("page_title") or context.get("brief") or site_name
        brief = context.get("brief") or context.get("page_excerpt") or site_tagline
        keywords = context.get("keywords") or []
        keyword_line = ", ".join(keywords[:3])

        title = _sentence_case(page_title)
        hero_heading = title
        if goal == "hero_copy" and keyword_line:
            hero_heading = _sentence_case(f"{title} for {keyword_line}")

        hero_subheading = brief or f"{site_name} helps teams launch faster with cleaner publishing and commerce workflows."
        if keyword_line and keyword_line.lower() not in hero_subheading.lower():
            hero_subheading = f"{_compact_text(hero_subheading, 120)} Built for {keyword_line}."

        meta_title = title if site_name.lower() in title.lower() else f"{title} | {site_name}"
        meta_description = hero_subheading or f"Explore {site_name} and publish with a faster workflow."
        cta_label = "Start now" if goal == "hero_copy" else "Get started"

        return {
            "title": title,
            "meta_title": meta_title,
            "meta_description": meta_description,
            "hero_heading": hero_heading,
            "hero_subheading": hero_subheading,
            "cta_label": cta_label,
            "focus_keywords": keywords,
        }

    def _generate_blueprint_fallback(self, site, context: dict[str, Any]) -> dict[str, Any]:
        return {
            "site_name": context.get("site_name") or site.name,
            "site_tagline": context.get("site_tagline") or site.tagline or "",
            "positioning": context.get("brief") or site.description or site.tagline or "",
            "audience": context.get("audience") or "",
            "offering": context.get("offering") or site.tagline or "",
            "tone": context.get("tone") or "clear, premium, conversion-focused",
            "pages": _build_fallback_blueprint_pages(site, context),
        }


@transaction.atomic
def apply_site_blueprint(*, site, blueprint: dict[str, Any], sync_navigation: bool = True) -> dict[str, Any]:
    context = platform_app_registry.build_ai_context(BLUEPRINT_GOAL, site, None, {})
    normalized_blueprint = _normalize_blueprint(site, blueprint, context)
    created_pages: list[Page] = []
    existing_pages: list[Page] = []
    pages_by_plan_id: dict[str, Page] = {}

    for page_plan in sorted(normalized_blueprint["pages"], key=lambda item: (not item["is_homepage"], item["path"], item["title"])):
        existing = site.pages.filter(path=page_plan["path"]).first()
        if existing:
            existing_pages.append(existing)
            pages_by_plan_id[page_plan["id"]] = existing
            continue

        html, css = build_page_markup_from_blueprint(page_plan, normalized_blueprint)
        page = Page.objects.create(
            site=site,
            title=page_plan["title"],
            slug=page_plan["slug"],
            path=page_plan["path"],
            is_homepage=page_plan["is_homepage"],
            seo=page_plan["seo"],
            html=html,
            css=css,
        )
        sync_homepage_state(page)
        ensure_unique_page_path(page)
        page.save()
        create_revision(page, "AI site blueprint starter")
        search_service.index_page(page)
        created_pages.append(page)
        pages_by_plan_id[page_plan["id"]] = page

    navigation_synced = False
    if sync_navigation:
        site.navigation = _build_navigation_items(normalized_blueprint, pages_by_plan_id)
        site.save(update_fields=["navigation", "updated_at"])
        navigation_synced = True

    homepage_page = site.pages.filter(is_homepage=True).order_by("id").first()
    return {
        "blueprint": normalized_blueprint,
        "created_pages": created_pages,
        "existing_pages": existing_pages,
        "homepage_page_id": homepage_page.id if homepage_page else None,
        "navigation_synced": navigation_synced,
    }


ai_service = AIService()
