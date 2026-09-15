"""Views owned by the project configuration package.

This module holds only the placeholder service root. The real pages arrive with
the template shell in TASK-UZK-006 and TASK-UZK-007.
"""

from __future__ import annotations

from django.http import HttpRequest, HttpResponse


def service_root(request: HttpRequest) -> HttpResponse:
    """Answer the root URL so the running application can be verified.

    This is a deliberate placeholder for TASK-UZK-001, whose only job is to
    prove the application starts and responds. It is replaced by the real
    dashboard once the template shell exists.
    """
    return HttpResponse(
        "Uz-Koram | Xarid Xizmati Bo'limi \u2014 application skeleton is running.",
        content_type="text/plain; charset=utf-8",
    )
