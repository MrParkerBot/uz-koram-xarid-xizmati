"""Telling people what has happened to what they sent, and what now waits for them.

Two directions. A requester is told each time their purchase request moves a
step along DEC-016's chain (REQ-ARIZA-004, 005), and the people it has just
landed on are told that it is theirs to act on, so nobody has to open a page
to find out whether anything arrived.

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
from collections.abc import Callable

from django.contrib.auth.models import AbstractBaseUser
from django.db import DatabaseError

from django.contrib.auth import get_user_model

from xarid.models import (
    BOLIM_BOSHLIGI,
    DIREKTOR,
    Application,
    Contract,
    ContractComment,
    Notification,
    PurchaseApplication,
    purchasing_department_head,
    purchasing_department_workers,
    users_of_type,
)

logger = logging.getLogger(__name__)


def deliver(build: Callable[[], Notification]) -> Notification | None:
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


def what_it_is_about(purchase_application: PurchaseApplication) -> str:
    """The line under the heading: enough to act on without opening the page."""
    requester = purchase_application.created_by

    return (
        f"{purchase_application.shartnoma_nomi} - "
        f"{purchase_application.department.name}, "
        f"{requester.get_full_name() or requester.get_username()}"
    )


def tell_whoever_it_now_waits_for(
    purchase_application: PurchaseApplication,
) -> list[Notification]:
    """Tell the people a purchase request has just landed on.

    Each step of DEC-016's chain hands it to a different group: the
    requester's own Bo`lim Boshlig`i, then any Direktor, then Xarid Bo`limi's
    head and Menejer, who take the approved request up. A request that has
    been refused, or that waits for nobody, tells nobody.

    The requester is never among them. Somebody does not need telling that
    the thing they just did is waiting for them, and a head may raise a
    request of their own department's.

    Returns:
        The notifications written; empty when there is nobody to tell, which
        is an ordinary state - a department with no head yet, or no
        purchasing department named.
    """
    stage = purchase_application.stage

    if stage == PurchaseApplication.Stage.AWAITING_HEAD:
        recipients = users_of_type(BOLIM_BOSHLIGI, department=purchase_application.department)
        kind = Notification.Kind.PURCHASE_AWAITING_YOU
    elif stage == PurchaseApplication.Stage.AWAITING_DIREKTOR:
        recipients = users_of_type(DIREKTOR)
        kind = Notification.Kind.PURCHASE_AWAITING_YOU
    elif stage == PurchaseApplication.Stage.APPROVED:
        recipients = purchasing_department_workers()
        kind = Notification.Kind.PURCHASE_ARRIVED
    else:
        return []

    waiting = [
        person for person in recipients if person.pk != purchase_application.created_by_id
    ]
    if not waiting:
        return []

    written = deliver(
        lambda: Notification.objects.bulk_create(
            [
                Notification(
                    recipient=person,
                    purchase_application=purchase_application,
                    kind=kind,
                    izoh=what_it_is_about(purchase_application),
                )
                for person in waiting
            ]
        )
    )

    return written or []


def tell_requester_of_progress(
    purchase_application: PurchaseApplication,
) -> Notification | None:
    """Tell a requester their request has moved a step along the chain.

    Which step it reached decides the wording: the head's approval sends it
    to the Direktor, and the Direktor's finishes it and raises the
    department's own application. A refusal is told by
    Notification.tell_requester_of_rejection(), which carries the reason.
    """
    kinds = {
        PurchaseApplication.Stage.AWAITING_DIREKTOR: (
            Notification.Kind.PURCHASE_APPROVED_BY_HEAD
        ),
        PurchaseApplication.Stage.APPROVED: Notification.Kind.PURCHASE_APPROVED,
    }
    kind = kinds.get(purchase_application.stage)
    if kind is None:
        return None

    return deliver(
        lambda: Notification.objects.create(
            recipient=purchase_application.created_by,
            purchase_application=purchase_application,
            kind=kind,
            izoh=what_it_is_about(purchase_application),
        )
    )


def what_the_contract_is(contract: Contract) -> str:
    """The line under the heading: enough to act on without opening the page.

    The contract's own number, the firma behind it, and the status it now
    stands at. The notification hangs off the application, so without this
    line the reader is told an ariza number and left to guess which contract
    of it moved - and, for a move, where it moved to.

    A contract with no status yet says so rather than trailing a comma.
    """
    standing = contract.status.name if contract.status else "holat belgilanmagan"

    return f"{contract.shartnoma_raqami} - {contract.supplier.name}, {standing}"


def tell_of_contract_sent(
    contract: Contract, by: AbstractBaseUser
) -> list[Notification]:
    """Tell Xarid Bo`limi that a contract now waits for a decision.

    Its Bo`lim Boshlig`i and its Menejer: the people Tuzilgan Shartnomalar
    belongs to, and so the people a sent contract has landed on. The sender
    is not among them even when they hold one of those roles - somebody does
    not need telling that the thing they just did is waiting for them, which
    is the rule tell_whoever_it_now_waits_for() already works to.

    Called after the send reported success, so a refused send tells nobody.

    Returns:
        The notifications written; empty when there is nobody to tell, which
        is an ordinary state - no purchasing department named yet, or its
        only head is the person who sent this.
    """
    waiting = [
        person for person in purchasing_department_workers() if person.pk != by.pk
    ]
    if not waiting:
        return []

    about = what_the_contract_is(contract)
    written = deliver(
        lambda: Notification.objects.bulk_create(
            [
                Notification(
                    recipient=person,
                    application=contract.application,
                    kind=Notification.Kind.CONTRACT_SENT,
                    izoh=about,
                )
                for person in waiting
            ]
        )
    )

    return written or []


def tell_head_of_status_change(
    contract: Contract, by: AbstractBaseUser
) -> list[Notification]:
    """Tell Xarid Bo`limi's head that a contract has moved a step.

    The head alone, not the Menejer: a status moving is progress on work the
    head handed out, while the Menejer hears when a contract is actually
    sent. The sender of the move is never told about their own click, which
    is the rule the rest of this module works to.

    Called after the move reported success, so a status that did not change
    - the drop-down left where it was - tells nobody.

    Returns:
        The notifications written; empty when there is nobody to tell.
    """
    waiting = [person for person in purchasing_department_head() if person.pk != by.pk]
    if not waiting:
        return []

    about = what_the_contract_is(contract)
    written = deliver(
        lambda: Notification.objects.bulk_create(
            [
                Notification(
                    recipient=person,
                    application=contract.application,
                    kind=Notification.Kind.CONTRACT_STATUS_CHANGED,
                    izoh=about,
                )
                for person in waiting
            ]
        )
    )

    return written or []


def tell_thread_of_comment(
    contract: Contract, comment: ContractComment
) -> list[Notification]:
    """Tell the people in a contract's conversation that it has moved on.

    Two groups, which usually overlap: whoever the contract belongs to, and
    whoever has already written on it. The first because a comment about
    their work that they are never told about is a comment nobody reads;
    the second because somebody who asked a question is the person waiting
    for the answer.

    The author is never among them, and nobody is told twice however many
    ways they qualify.

    Returns:
        The notifications written; empty when the author is the only person
        the contract concerns, which is ordinary.
    """
    spoken = get_user_model().objects.filter(
        contract_comments__contract=contract, is_active=True
    )

    listening = {
        person.pk: person
        for person in (*contract.holders(), *spoken)
        if person.pk != comment.author_id and person.is_active
    }
    if not listening:
        return []

    # The text travels with it: a notification saying only that somebody
    # commented is one that has to be opened to learn anything.
    about = f"{contract.shartnoma_raqami}: {comment.matn}"
    written = deliver(
        lambda: Notification.objects.bulk_create(
            [
                Notification(
                    recipient=person,
                    application=contract.application,
                    kind=Notification.Kind.CONTRACT_COMMENTED,
                    izoh=about,
                )
                for person in listening.values()
            ]
        )
    )

    return written or []


def tell_holders_of_decision(
    contract: Contract,
    by: AbstractBaseUser,
    kind: str,
    comment: str = "",
) -> list[Notification]:
    """Tell whoever the contract belongs to what was decided about it.

    The specialist it was assigned to and whoever entered it - holders() has
    the rule - minus the person who decided, who does not need telling what
    they just did. A rejection carries its reason: a contract that comes
    back with no explanation is one somebody has to go and ask about, which
    is the thing REQ-SHARTNOMA-004 gives the comment for.

    Called after the transition reported success, so a decision that was
    refused tells nobody.

    Args:
        contract: the contract decided on.
        by: who decided.
        kind: which of the decision notifications this is.
        comment: the reason, for the decisions that carry one.

    Returns:
        The notifications written; empty when the decider is the only person
        the contract concerns.
    """
    listening = [
        person
        for person in contract.holders()
        if person.pk != by.pk and person.is_active
    ]
    if not listening:
        return []

    about = what_the_contract_is(contract)
    if comment:
        about = f"{about} - {comment}"

    written = deliver(
        lambda: Notification.objects.bulk_create(
            [
                Notification(
                    recipient=person,
                    application=contract.application,
                    kind=kind,
                    izoh=about,
                )
                for person in listening
            ]
        )
    )

    return written or []


def unread_for(user) -> int:
    """How many notifications this person has not been shown yet.

    Zero for an anonymous visitor, so the header can ask without checking
    first.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return 0

    return Notification.objects.filter(recipient=user, read_at__isnull=True).count()
