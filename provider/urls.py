from __future__ import annotations

from django.urls import path

from provider.views import (
    AIBlogDraftView,
    AIFAQSchemaView,
    AIGenerationView,
    AIImageAltTextView,
    AIJobDetailView,
    AIJobListView,
    AIPageOutlineView,
    AIProductDescriptionView,
    AISectionCompositionView,
    AISEOMetadataView,
    AIUsageSummaryView,
    DNSVerificationInstructionsView,
    ImageTransformView,
    ProviderCatalogView,
)

urlpatterns = [
    path("provider/catalog/", ProviderCatalogView.as_view(), name="provider-catalog"),
    path("provider/image/transform/", ImageTransformView.as_view(), name="provider-image-transform"),
    path("provider/dns/instructions/", DNSVerificationInstructionsView.as_view(), name="provider-dns-instructions"),
    path("provider/ai/generate/", AIGenerationView.as_view(), name="provider-ai-generate"),
    path("provider/ai/page-outline/", AIPageOutlineView.as_view(), name="provider-ai-page-outline"),
    path("provider/ai/blog-draft/", AIBlogDraftView.as_view(), name="provider-ai-blog-draft"),
    path(
        "provider/ai/product-description/",
        AIProductDescriptionView.as_view(),
        name="provider-ai-product-description",
    ),
    path("provider/ai/seo-meta/", AISEOMetadataView.as_view(), name="provider-ai-seo-meta"),
    path("provider/ai/image-alt/", AIImageAltTextView.as_view(), name="provider-ai-image-alt"),
    path("provider/ai/faq-schema/", AIFAQSchemaView.as_view(), name="provider-ai-faq-schema"),
    path(
        "provider/ai/section-composition/",
        AISectionCompositionView.as_view(),
        name="provider-ai-section-composition",
    ),
    path("provider/ai/jobs/", AIJobListView.as_view(), name="provider-ai-jobs"),
    path("provider/ai/jobs/<int:job_id>/", AIJobDetailView.as_view(), name="provider-ai-job-detail"),
    path("provider/ai/usage/", AIUsageSummaryView.as_view(), name="provider-ai-usage"),
]
