"""
Search Services - Meilisearch Integration

Provides instant search across pages, posts, products, and media.
Uses Meilisearch for fast, typo-tolerant search with faceting.
"""

import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class SearchService:
    """
    Search service using Meilisearch for instant search.
    
    Indexes: pages, posts, products, media
    Features: typo tolerance, faceting, filtering, highlighting
    """
    
    def __init__(self):
        """Initialize Meilisearch client if configured."""
        self.client = None
        self.enabled = False
        self._setup_lock = threading.Lock()
        self._settings_last_synced_at = 0.0
        self._settings_sync_interval_seconds = max(
            60,
            int(os.environ.get("MEILISEARCH_SETTINGS_SYNC_INTERVAL_SECONDS", "300") or "300"),
        )
        
        try:
            from meilisearch import Client
            
            host = os.environ.get('MEILISEARCH_HOST', 'http://127.0.0.1:7700')
            api_key = os.environ.get('MEILISEARCH_API_KEY', '')
            
            if host:
                self.client = Client(host, api_key)
                self.enabled = True
                logger.info(f"Meilisearch client initialized: {host}")
        except ImportError:
            logger.warning("meilisearch-python not installed. Search disabled.")
        except Exception as e:
            logger.warning(f"Failed to initialize Meilisearch: {e}")
    
    def index_page(self, page) -> bool:
        """Index a page for search."""
        if not self.enabled:
            return False
        
        try:
            index = self.client.index('pages')
            
            document = {
                'id': f"page_{page.id}",
                'type': 'page',
                'site_id': page.site.id,
                'site_name': page.site.name,
                'title': page.title,
                'slug': page.slug,
                'path': page.path,
                'status': page.status,
                'content': self._extract_text_from_html(page.html),
                'seo_title': page.seo.get('meta_title', ''),
                'seo_description': page.seo.get('meta_description', ''),
                'created_at': page.created_at.timestamp(),
                'updated_at': page.updated_at.timestamp(),
            }
            
            index.add_documents([document])
            return True
        except Exception as e:
            logger.error(f"Failed to index page {page.id}: {e}")
            return False
    
    def index_post(self, post) -> bool:
        """Index a blog post for search."""
        if not self.enabled:
            return False
        
        try:
            index = self.client.index('posts')
            
            document = {
                'id': f"post_{post.id}",
                'type': 'post',
                'site_id': post.site.id,
                'site_name': post.site.name,
                'title': post.title,
                'slug': post.slug,
                'excerpt': post.excerpt,
                'content': self._extract_text_from_html(post.body_html),
                'status': post.status,
                'categories': [cat.name for cat in post.categories.all()],
                'tags': [tag.name for tag in post.tags.all()],
                'created_at': post.created_at.timestamp(),
                'updated_at': post.updated_at.timestamp(),
                'published_at': post.published_at.timestamp() if post.published_at else None,
            }
            
            index.add_documents([document])
            return True
        except Exception as e:
            logger.error(f"Failed to index post {post.id}: {e}")
            return False
    
    def index_product(self, product) -> bool:
        """Index a product for search."""
        if not self.enabled:
            return False
        
        try:
            index = self.client.index('products')
            
            # Get price range from variants
            variants = product.variants.all()
            prices = [float(v.price) for v in variants if v.is_active]
            
            document = {
                'id': f"product_{product.id}",
                'type': 'product',
                'site_id': product.site.id,
                'site_name': product.site.name,
                'title': product.title,
                'slug': product.slug,
                'excerpt': product.excerpt,
                'description': self._extract_text_from_html(product.description_html),
                'status': product.status,
                'categories': [cat.name for cat in product.categories.all()],
                'is_featured': product.is_featured,
                'price_min': min(prices) if prices else 0,
                'price_max': max(prices) if prices else 0,
                'in_stock': any(v.inventory > 0 for v in variants if v.track_inventory),
                'created_at': product.created_at.timestamp(),
                'updated_at': product.updated_at.timestamp(),
            }
            
            index.add_documents([document])
            return True
        except Exception as e:
            logger.error(f"Failed to index product {product.id}: {e}")
            return False
    
    def index_media(self, media) -> bool:
        """Index media asset for search."""
        if not self.enabled:
            return False
        
        try:
            index = self.client.index('media')
            
            document = {
                'id': f"media_{media.id}",
                'type': 'media',
                'site_id': media.site.id,
                'site_name': media.site.name,
                'title': media.title,
                'alt_text': media.alt_text,
                'caption': media.caption,
                'kind': media.kind,
                'file_url': media.file.url if media.file else '',
                'created_at': media.created_at.timestamp(),
            }
            
            index.add_documents([document])
            return True
        except Exception as e:
            logger.error(f"Failed to index media {media.id}: {e}")
            return False
    
    def search(
        self,
        query: str,
        index_name: str = 'pages',
        filters: Optional[str] = None,
        limit: int = 20,
        site_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Search across indexed content.
        
        Args:
            query: Search query
            index_name: Index to search (pages, posts, products, media)
            filters: Meilisearch filter string
            limit: Max results
            site_id: Filter by site ID
        
        Returns:
            Search results with hits and metadata
        """
        if not self.enabled:
            return {'hits': [], 'total': 0}
        
        try:
            index = self.client.index(index_name)
            
            # Build filters
            filter_parts = []
            if site_id:
                filter_parts.append(f"site_id = {site_id}")
            if filters:
                filter_parts.append(filters)
            
            filter_str = ' AND '.join(filter_parts) if filter_parts else None
            
            results = index.search(
                query,
                {
                    'filter': filter_str,
                    'limit': limit,
                    'attributesToHighlight': ['title', 'content', 'description'],
                }
            )
            
            return {
                'hits': results['hits'],
                'total': results['estimatedTotalHits'],
                'query': query,
                'processing_time_ms': results['processingTimeMs'],
            }
        except Exception as e:
            logger.error(f"Search failed: {e}")
            return {'hits': [], 'total': 0, 'error': str(e)}
    
    def search_all(
        self,
        query: str,
        site_id: Optional[int] = None,
        limit_per_index: int = 5
    ) -> Dict[str, Any]:
        """Search across all indexes."""
        if not self.enabled:
            return {}
        
        results = {}
        for index_name in ['pages', 'posts', 'products', 'media']:
            results[index_name] = self.search(
                query,
                index_name=index_name,
                site_id=site_id,
                limit=limit_per_index
            )
        
        return results
    
    def delete_document(self, index_name: str, doc_id: str) -> bool:
        """Delete a document from search index."""
        if not self.enabled:
            return False
        
        try:
            index = self.client.index(index_name)
            index.delete_document(doc_id)
            return True
        except Exception as e:
            logger.error(f"Failed to delete document {doc_id}: {e}")
            return False
    
    def setup_indexes(self, *, force: bool = False) -> bool:
        """Set up search indexes with proper settings."""
        if not self.enabled:
            return False
        now = time.monotonic()
        if not force and (now - self._settings_last_synced_at) < self._settings_sync_interval_seconds:
            return True
        if not self._setup_lock.acquire(blocking=False):
            return True
        
        try:
            now = time.monotonic()
            if not force and (now - self._settings_last_synced_at) < self._settings_sync_interval_seconds:
                return True
            # Pages index
            pages_index = self.client.index('pages')
            pages_index.update_settings({
                'searchableAttributes': ['title', 'content', 'seo_title', 'seo_description'],
                'filterableAttributes': ['site_id', 'status', 'type'],
                'sortableAttributes': ['created_at', 'updated_at'],
                'displayedAttributes': ['id', 'title', 'slug', 'path', 'status', 'site_name'],
            })
            
            # Posts index
            posts_index = self.client.index('posts')
            posts_index.update_settings({
                'searchableAttributes': ['title', 'content', 'excerpt'],
                'filterableAttributes': ['site_id', 'status', 'categories', 'tags'],
                'sortableAttributes': ['created_at', 'published_at'],
                'displayedAttributes': ['id', 'title', 'slug', 'excerpt', 'status', 'categories', 'tags'],
            })
            
            # Products index
            products_index = self.client.index('products')
            products_index.update_settings({
                'searchableAttributes': ['title', 'description', 'excerpt'],
                'filterableAttributes': ['site_id', 'status', 'categories', 'is_featured', 'in_stock'],
                'sortableAttributes': ['created_at', 'price_min', 'price_max'],
                'displayedAttributes': ['id', 'title', 'slug', 'price_min', 'price_max', 'in_stock'],
            })
            
            # Media index
            media_index = self.client.index('media')
            media_index.update_settings({
                'searchableAttributes': ['title', 'alt_text', 'caption'],
                'filterableAttributes': ['site_id', 'kind'],
                'sortableAttributes': ['created_at'],
                'displayedAttributes': ['id', 'title', 'kind', 'file_url'],
            })
            
            logger.info("Search indexes configured successfully")
            self._settings_last_synced_at = time.monotonic()
            return True
        except Exception as e:
            logger.error(f"Failed to setup indexes: {e}")
            return False
        finally:
            self._setup_lock.release()
    
    def _extract_text_from_html(self, html: str) -> str:
        """Extract plain text from HTML for indexing."""
        if not html:
            return ''
        
        try:
            from html.parser import HTMLParser
            
            class TextExtractor(HTMLParser):
                def __init__(self):
                    super().__init__()
                    self.text = []
                
                def handle_data(self, data):
                    self.text.append(data.strip())
            
            parser = TextExtractor()
            parser.feed(html)
            return ' '.join(parser.text)
        except Exception:
            return html[:1000]  # Fallback to truncated HTML


# Global search service instance
search_service = SearchService()
