"""FSM state groups."""

from app.bot.states.procurement import ProcurementCreation, ProcurementEditing
from app.bot.states.purchase_request import RequestCreation, RequestModeration
from app.bot.states.users import AddPurchaser

__all__ = [
    "AddPurchaser",
    "ProcurementCreation",
    "ProcurementEditing",
    "RequestCreation",
    "RequestModeration",
]
