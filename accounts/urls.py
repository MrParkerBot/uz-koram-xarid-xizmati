"""The routes of the pages accounts owns: users, types and specialties.

Included by the root URL configuration at no prefix and with no namespace,
so every path and every name here is the one the templates, the reverse()
calls and the permission matrix already use.
"""

from django.urls import path

from accounts.permissions import require_page_permission
from accounts.specialty_views import (
    specialty_create,
    specialty_delete,
    specialty_list,
    specialty_update,
)
from accounts.type_views import (
    user_type_create,
    user_type_delete,
    user_type_list,
    user_type_update,
)
from accounts.views import (
    user_contract_editing,
    user_create,
    user_delete,
    user_list,
    user_update,
)

urlpatterns = [
    # The Users page has real views rather than a template: it is the first
    # page with data behind it (TASK-UZK-011). The list keeps the name the
    # sidebar and the page inventory already use.
    # The Users page and everything it does answer to the same permission as
    # the page itself: an action must not be reachable by somebody who may not
    # open the page that offers it.
    path("users/", require_page_permission("users")(user_list), name="users"),
    path(
        "users/add/",
        require_page_permission("users")(user_create),
        name="user-create",
    ),
    path(
        "users/<int:pk>/edit/",
        require_page_permission("users")(user_update),
        name="user-update",
    ),
    path(
        "users/<int:pk>/delete/",
        require_page_permission("users")(user_delete),
        name="user-delete",
    ),
    # The User Specialty master data page (TASK-UZK-014), the first of the
    # eight pages section 3 describes in the same shape.
    path(
        "user-specialty/",
        require_page_permission("user-specialty")(specialty_list),
        name="user-specialty",
    ),
    path(
        "user-specialty/add/",
        require_page_permission("user-specialty")(specialty_create),
        name="user-specialty-create",
    ),
    path(
        "user-specialty/<int:pk>/edit/",
        require_page_permission("user-specialty")(specialty_update),
        name="user-specialty-update",
    ),
    path(
        "user-specialty/<int:pk>/delete/",
        require_page_permission("user-specialty")(specialty_delete),
        name="user-specialty-delete",
    ),
    # The User Types master data page (TASK-UZK-015). A type is also a role,
    # so the six DEC-013 fixes cannot be renamed or deleted here.
    path(
        "user-types/",
        require_page_permission("user-types")(user_type_list),
        name="user-types",
    ),
    path(
        "user-types/add/",
        require_page_permission("user-types")(user_type_create),
        name="user-types-create",
    ),
    path(
        "user-types/<int:pk>/edit/",
        require_page_permission("user-types")(user_type_update),
        name="user-types-update",
    ),
    path(
        "user-types/<int:pk>/delete/",
        require_page_permission("user-types")(user_type_delete),
        name="user-types-delete",
    ),
    path(
        "users/<int:pk>/contract-editing/",
        require_page_permission("users")(user_contract_editing),
        name="user-contract-editing",
    ),
]
