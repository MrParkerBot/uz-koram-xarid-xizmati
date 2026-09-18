"""Telling a requester what happened to what they sent (REQ-ARIZA-004, 005).

Delivery is in-app and nothing else: an entry in the panel and a number on
the bell (DEC-012). There is no email and no SMS to fail, but a write can
still fail, and the acceptance criterion is explicit that a failure must not
undo the decision it followed. So every call goes through deliver(), which
catches the failure, writes it to the server log and returns None.

That ordering matters as much as it does for the audit log: these are called
after the transition reported success, so a refused decision tells nobody
that it happened.
"""

from __future__ import annotations

import logging

from django.db import DatabaseError

from xarid.models import Application, Notification

logger = logging.getLogger(__name__)


def deliver(build) -> Notification | None:
    """Write one notification, or log why it could not be written.

    Args:
        build: a callable producing the notification.

    Returns:
        The notification, or None when it could not be written. None rather
        than an exception: the decision that prompted it has already
        happened, and refusing to report it is not a reason to undo it.
    """
    try:
        return build()
    except DatabaseError:
        logger.exception("A notification could not be delivered.")
        return None


def tell_sender_of_acceptance(application: Application) -> Notification | None:
    """Tell the requester their application was accepted (REQ-ARIZA-004).

    Does nothing when the application has no sender. One created on the
    Qabul qilingan page is entered by the department itself and has no
    requester behind it (DEC-031), so there is nobody to tell.
    """
    if application.sender_id is None:
        return None

    return deliver(
        lambda: Notification.objects.create(
            recipient=application.sender,
            application=application,
            kind=Notification.Kind.APPLICATION_ACCEPTED,
        )
    )


def tell_sender_of_refusal(application: Application) -> Notification | None:
    """Tell the requester their application was refused, and why.

    The comment is copied rather than read back from the application: what
    the sender was told is what the decision said at the time.
    """
    if application.sender_id is None:
        return None

    return deliver(
        lambda: Notification.objects.create(
            recipient=application.sender,
            application=application,
            kind=Notification.Kind.APPLICATION_REJECTED,
            izoh=application.inkor_izohi,
        )
    )


def unread_for(user) -> int:
    """How many notifications this person has not been shown yet.

    Zero for an anonymous visitor, so the header can ask without checking
    first.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return 0

    return Notification.objects.filter(recipient=user, read_at__isnull=True).count()
