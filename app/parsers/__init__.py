"""Deterministic text parsers (swappable via protocols)."""

from app.parsers.base import (
    ParsedItem,
    ParsedProcurement,
    ParseError,
    ParseResult,
    ProcurementParserProtocol,
    PurchaseListFileParserProtocol,
    PurchaseListParserProtocol,
)
from app.parsers.excel_list_parser import ExcelPurchaseListParser, get_default_excel_parser
from app.parsers.procurement_parser import RegexProcurementParser
from app.parsers.purchase_list_parser import (
    RegexPurchaseListParser,
    get_default_purchase_list_parser,
)

__all__ = [
    "ExcelPurchaseListParser",
    "ParseError",
    "ParseResult",
    "ParsedItem",
    "ParsedProcurement",
    "ProcurementParserProtocol",
    "PurchaseListFileParserProtocol",
    "PurchaseListParserProtocol",
    "RegexProcurementParser",
    "RegexPurchaseListParser",
    "get_default_excel_parser",
    "get_default_purchase_list_parser",
]
