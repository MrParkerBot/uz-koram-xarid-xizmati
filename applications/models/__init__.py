"""The work the department does, rather than the lists that describe it.

accounts holds facts about people and reference holds the maintainable lists.
An application is neither: it is a record with a life cycle, and it is the
first thing here that has one.

TASK-UZK-022 builds the record and the incoming list; TASK-UZK-023 and
TASK-UZK-024 are the two decisions taken on it there, and TASK-UZK-025 to
TASK-UZK-027 carry an accepted one onward.

TASK-UZK-026 splits the record in two. What an application orders is an
ApplicationItem now rather than four columns on the application, because
REQ-ARIZA-010's plus button means one application can order several things.
"""

from applications.models.application import (
    ARIZA_NUMBER_DIGITS,
    ARIZA_NUMBER_PREFIX,
    SMALLEST_QUANTITY,
    Application,
    ApplicationItem,
    OrderLine,
    next_ariza_raqami,
    next_number,
)
from applications.models.contract import (
    CONTRACT_NUMBER_PREFIX,
    SMALLEST_PRICE,
    SOUM,
    Contract,
    ContractItem,
    contract_value_of,
    money_display,
    next_shartnoma_raqami,
)
from applications.models.purchase import (
    XARID_NUMBER_PREFIX,
    PurchaseApplication,
    PurchaseApplicationItem,
    next_xarid_raqami,
)

__all__ = [
    "ARIZA_NUMBER_DIGITS",
    "ARIZA_NUMBER_PREFIX",
    "CONTRACT_NUMBER_PREFIX",
    "SMALLEST_PRICE",
    "SMALLEST_QUANTITY",
    "SOUM",
    "XARID_NUMBER_PREFIX",
    "Application",
    "ApplicationItem",
    "Contract",
    "ContractItem",
    "OrderLine",
    "PurchaseApplication",
    "PurchaseApplicationItem",
    "contract_value_of",
    "money_display",
    "next_ariza_raqami",
    "next_number",
    "next_shartnoma_raqami",
    "next_xarid_raqami",
]
