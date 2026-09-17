"""The routes of the work itself: arizalar, contracts and purchase requests.

Included by the root URL configuration at no prefix and with no namespace,
so every path and every name here is the one the templates, the reverse()
calls and the permission matrix already use.
"""

from django.urls import path

from accounts.permissions import require_page_permission
from applications.application_views import (
    accept_application,
    accept_assigned_application,
    accepted_list,
    application_create,
    application_pdf,
    assign_application,
    assigned_list,
    incoming_list,
    reject_application,
    set_application_status,
)
from applications.contract_views import agreed_contracts_list, contract_create
from applications.purchase_views import (
    approve_purchase_application,
    purchase_application_create,
    purchase_application_list,
    purchase_application_original_pdf,
    purchase_application_pdf,
    reject_purchase_application,
)

urlpatterns = [
    # The Kelib tushgan Arizalar page (TASK-UZK-022), the first page with a
    # record that has a life cycle rather than a name. The PDF answers to the
    # same permission as the page, so an attachment is reachable by exactly
    # the people who may see the row it belongs to (DEC-019).
    path(
        "kelib-arizalar/",
        require_page_permission("kelib-arizalar")(incoming_list),
        name="kelib-arizalar",
    ),
    # The Qabul qilingan Arizalar page (TASK-UZK-025). It left PAGE_ROUTES
    # when it stopped being a template with no data behind it; the path and
    # the name are the ones the sidebar and PAGE_SHOWING_STAGE already use.
    path(
        "qabul-arizalar/",
        require_page_permission("qabul-arizalar")(accepted_list),
        name="qabul-arizalar",
    ),
    # The Tayinlangan Arizalar page (TASK-UZK-028). It left PAGE_ROUTES when
    # it stopped being a template with no data behind it; the path and the
    # name are the ones the sidebar, the permission matrix and
    # PAGE_SHOWING_STAGE already use.
    path(
        "tayinlangan/",
        require_page_permission("tayinlangan")(assigned_list),
        name="tayinlangan",
    ),
    # The specialist taking the work, and marking where it has got to
    # (TASK-UZK-029). Both are offered on the Tayinlangan page and answer to
    # its permission; which rows a caller may act on is decided in the view,
    # because a specialist may open the page and may not touch somebody
    # else's row.
    path(
        "tayinlangan/<int:pk>/qabul/",
        require_page_permission("tayinlangan")(accept_assigned_application),
        name="tayinlangan-qabul",
    ),
    path(
        "tayinlangan/<int:pk>/holat/",
        require_page_permission("tayinlangan")(set_application_status),
        name="tayinlangan-holat",
    ),
    # The Kelishinlingan Shartnoma page of section 4.6 (TASK-UZK-034). It
    # left PAGE_ROUTES when it stopped being a template with no data behind
    # it; the path and the name are the ones the sidebar and the permission
    # matrix already use.
    path(
        "kelishinlingan/",
        require_page_permission("kelishinlingan")(agreed_contracts_list),
        name="kelishinlingan",
    ),
    # Shartnoma Kiritish (TASK-UZK-035). Under the Kelishinlingan page's
    # own permission, because the form is on that page and whoever may
    # open it is whoever may enter a contract. REQ-SHARTNOMA-007's Cancel
    # has no route: it closes the window, and nothing is saved because
    # nothing was posted.
    path(
        "kelishinlingan/yaratish/",
        require_page_permission("kelishinlingan")(contract_create),
        name="shartnoma-yaratish",
    ),
    # The Xarid Arizasi page of section 4.9 (TASK-UZK-030). It left
    # PAGE_ROUTES when it stopped being a template with no data behind it; the
    # path and the name are the ones the sidebar and the permission matrix
    # already use. It is the only page a Users requester has.
    path(
        "xarid-ariza/",
        require_page_permission("xarid-ariza")(purchase_application_list),
        name="xarid-ariza",
    ),
    path(
        "xarid-ariza/yaratish/",
        require_page_permission("xarid-ariza")(purchase_application_create),
        name="xarid-ariza-yaratish",
    ),
    # DEC-016's approval chain (TASK-UZK-031). Both actions are offered in
    # the queue on the Xarid Arizasi page and answer to its permission;
    # whether this person is the one the request is waiting for is decided in
    # the view, because both approvers may open the page and only one of them
    # is waiting on any given request.
    path(
        "xarid-ariza/<int:pk>/tasdiqlash/",
        require_page_permission("xarid-ariza")(approve_purchase_application),
        name="xarid-ariza-tasdiqlash",
    ),
    path(
        "xarid-ariza/<int:pk>/inkor/",
        require_page_permission("xarid-ariza")(reject_purchase_application),
        name="xarid-ariza-inkor",
    ),
    path(
        "xarid-ariza/<int:pk>/pdf/",
        require_page_permission("xarid-ariza")(purchase_application_pdf),
        name="xarid-ariza-pdf",
    ),
    # The attachment as it was uploaded, before an approval stamped it
    # (TASK-UZK-032). Same permission as the stamped one: anybody who may see
    # the approved document may see what it was approved from.
    path(
        "xarid-ariza/<int:pk>/asl-pdf/",
        require_page_permission("xarid-ariza")(
            purchase_application_original_pdf
        ),
        name="xarid-ariza-asl-pdf",
    ),
    # Creating an application (TASK-UZK-026). The form is on the Qabul
    # qilingan page, so it answers to that page's permission like every other
    # action: whoever may not see the page may not create a record on it.
    path(
        "qabul-arizalar/yaratish/",
        require_page_permission("qabul-arizalar")(application_create),
        name="ariza-yaratish",
    ),
    # Not wrapped in require_page_permission: the view asks about the page
    # that currently shows this application, because the attachment has to
    # stop being reachable when the row stops being visible.
    path(
        "arizalar/<int:pk>/pdf/",
        application_pdf,
        name="ariza-pdf",
    ),
    # Accepting is offered on the incoming page, so it answers to that page's
    # permission: an action is never reachable by somebody who may not see
    # the row offering it (TASK-UZK-023).
    path(
        "kelib-arizalar/<int:pk>/qabul/",
        require_page_permission("kelib-arizalar")(accept_application),
        name="ariza-qabul",
    ),
    # Assigning and re-assigning, offered on the Qabul qilingan page and
    # answering to its permission (TASK-UZK-027). One route for both, because
    # DEC-024 makes them the same act.
    path(
        "qabul-arizalar/<int:pk>/tayinlash/",
        require_page_permission("qabul-arizalar")(assign_application),
        name="ariza-tayinlash",
    ),
    # Rejecting, for the same reason and under the same permission
    # (TASK-UZK-024).
    path(
        "kelib-arizalar/<int:pk>/inkor/",
        require_page_permission("kelib-arizalar")(reject_application),
        name="ariza-inkor",
    ),
]
