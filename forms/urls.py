"""Forms domain API routes."""

from __future__ import annotations

from django.urls import include, path
from rest_framework.routers import SimpleRouter

from forms.views import (
    FormSubmissionViewSet,
    FormViewSet,
    PublicFormSubmissionView,
    PublicFormView,
    PublicRuntimeFormSchemaView,
    PublicRuntimeFormSubmissionView,
)

router = SimpleRouter()
router.register("forms", FormViewSet, basename="form")
router.register("submissions", FormSubmissionViewSet, basename="submission")

urlpatterns = [
    path("public/forms/submit/", PublicFormSubmissionView.as_view(), name="public-form-submit"),
    path("public/forms/<slug:site_slug>/<slug:form_slug>/", PublicFormView.as_view(), name="public-form-view"),
    path(
        "public/forms/<slug:site_slug>/<slug:form_slug>/submit/",
        PublicFormView.as_view(),
        name="public-form-submit-new",
    ),
    path("public/runtime/forms/<slug:form_slug>/", PublicRuntimeFormSchemaView.as_view(), name="runtime-form-schema"),
    path(
        "public/runtime/forms/<slug:form_slug>/submit/",
        PublicRuntimeFormSubmissionView.as_view(),
        name="runtime-form-submit",
    ),
    path("", include(router.urls)),
]

