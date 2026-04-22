from __future__ import annotations

from typing import Any

from django.db import models

from analytics.models import SearchDocument


class SearchIndexService:
    """Shared abstraction over the active search backend with DB fallback."""

    @property
    def backend(self):
        from builder.search_services import search_service

        return search_service

    def is_enabled(self) -> bool:
        return bool(getattr(self.backend, "enabled", False))

    def ensure_indexes(self) -> bool:
        backend = self.backend
        setup = getattr(backend, "setup_indexes", None)
        if callable(setup):
            return bool(setup())
        return False

    def _document_id(self, object_type: str, object_id: int) -> str:
        return f"{object_type}_{int(object_id)}"

    def _upsert_db_document(
        self,
        *,
        site_id: int,
        index_name: str,
        external_id: str,
        title: str = "",
        path: str = "",
        content: str = "",
        summary: str = "",
        metadata: dict[str, Any] | None = None,
        source_updated_at=None,
    ) -> SearchDocument:
        document, _ = SearchDocument.objects.update_or_create(
            site_id=site_id,
            index_name=index_name,
            external_id=external_id,
            defaults={
                "title": title[:255],
                "path": path[:255],
                "content": content[:20_000],
                "summary": summary[:3000],
                "metadata": metadata or {},
                "source_updated_at": source_updated_at,
            },
        )
        return document

    def _delete_db_document(self, *, index_name: str, external_id: str) -> None:
        SearchDocument.objects.filter(index_name=index_name, external_id=external_id).delete()

    def index_page(self, page) -> bool:
        external_id = self._document_id("page", page.id)
        self._upsert_db_document(
            site_id=page.site_id,
            index_name="pages",
            external_id=external_id,
            title=page.title,
            path=page.path,
            content=page.html or "",
            summary=(page.seo or {}).get("meta_description", ""),
            metadata={"slug": page.slug, "status": page.status},
            source_updated_at=page.updated_at,
        )
        return bool(self.backend.index_page(page)) if self.is_enabled() else True

    def index_post(self, post) -> bool:
        external_id = self._document_id("post", post.id)
        self._upsert_db_document(
            site_id=post.site_id,
            index_name="posts",
            external_id=external_id,
            title=post.title,
            path=f"/blog/{post.slug}/",
            content=post.body_html or "",
            summary=post.excerpt or "",
            metadata={"slug": post.slug, "status": post.status},
            source_updated_at=post.updated_at,
        )
        return bool(self.backend.index_post(post)) if self.is_enabled() else True

    def index_product(self, product) -> bool:
        external_id = self._document_id("product", product.id)
        self._upsert_db_document(
            site_id=product.site_id,
            index_name="products",
            external_id=external_id,
            title=product.title,
            path=f"/shop/{product.slug}/",
            content=product.description_html or "",
            summary=product.excerpt or "",
            metadata={"slug": product.slug, "status": product.status},
            source_updated_at=product.updated_at,
        )
        return bool(self.backend.index_product(product)) if self.is_enabled() else True

    def index_media(self, media) -> bool:
        external_id = self._document_id("media", media.id)
        self._upsert_db_document(
            site_id=media.site_id,
            index_name="media",
            external_id=external_id,
            title=media.title,
            path=getattr(media.file, "name", ""),
            content=media.caption or "",
            summary=media.alt_text or "",
            metadata={"kind": media.kind, "mime_type": media.mime_type},
            source_updated_at=media.updated_at,
        )
        return bool(self.backend.index_media(media)) if self.is_enabled() else True

    def index_document(self, index_name: str, document: dict[str, Any]) -> bool:
        normalized_index = str(index_name or "").strip().lower()
        if not normalized_index:
            return False
        external_id = str(document.get("id") or document.get("external_id") or "").strip()
        site_id = int(document.get("site_id") or 0)
        if not external_id or site_id <= 0:
            return False
        self._upsert_db_document(
            site_id=site_id,
            index_name=normalized_index,
            external_id=external_id,
            title=str(document.get("title") or ""),
            path=str(document.get("path") or ""),
            content=str(document.get("content") or ""),
            summary=str(document.get("summary") or ""),
            metadata=document.get("metadata") if isinstance(document.get("metadata"), dict) else {},
            source_updated_at=document.get("source_updated_at"),
        )
        backend = self.backend
        if not getattr(backend, "enabled", False):
            return True
        try:
            backend.client.index(normalized_index).add_documents([document])
            return True
        except Exception:
            return False

    def delete_document(self, index_name: str, document_id: str) -> bool:
        self._delete_db_document(index_name=index_name, external_id=document_id)
        if not self.is_enabled():
            return True
        return bool(self.backend.delete_document(index_name, document_id))

    def _search_db(self, *, query: str, index_name: str, site_id: int | None = None, limit: int = 20) -> dict[str, Any]:
        queryset = SearchDocument.objects.filter(index_name=index_name)
        if site_id:
            queryset = queryset.filter(site_id=site_id)
        normalized_query = (query or "").strip()
        if normalized_query:
            queryset = queryset.filter(
                models.Q(title__icontains=normalized_query)
                | models.Q(path__icontains=normalized_query)
                | models.Q(content__icontains=normalized_query)
                | models.Q(summary__icontains=normalized_query)
            )
        results = list(queryset.order_by("-updated_at")[: max(1, min(limit, 200))])
        return {
            "hits": [
                {
                    "id": document.external_id,
                    "site_id": document.site_id,
                    "title": document.title,
                    "path": document.path,
                    "summary": document.summary,
                    "metadata": document.metadata,
                }
                for document in results
            ],
            "estimatedTotalHits": queryset.count(),
            "limit": limit,
        }

    def search(self, *, query: str, index_name: str, site_id: int | None = None, limit: int = 20) -> dict[str, Any]:
        if self.is_enabled():
            try:
                return self.backend.search(query=query, index_name=index_name, site_id=site_id, limit=limit)
            except Exception:
                pass
        return self._search_db(query=query, index_name=index_name, site_id=site_id, limit=limit)

    def search_all(self, *, query: str, site_id: int | None = None, limit_per_index: int = 5) -> dict[str, Any]:
        if self.is_enabled():
            try:
                return self.backend.search_all(query=query, site_id=site_id, limit_per_index=limit_per_index)
            except Exception:
                pass
        indexes = ("pages", "posts", "products", "media")
        return {
            index_name: self._search_db(
                query=query,
                index_name=index_name,
                site_id=site_id,
                limit=limit_per_index,
            )
            for index_name in indexes
        }


search_index = SearchIndexService()
