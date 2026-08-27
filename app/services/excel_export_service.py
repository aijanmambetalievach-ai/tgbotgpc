"""Excel generation (openpyxl).

Never called from a Telegram handler directly — handlers ask this service for
bytes and only then build a ``BufferedInputFile``.

Security: every string written to a cell goes through
:func:`app.domain.text.sanitize_excel_cell`, which neutralises formula
injection (``=``, ``+``, ``-``, ``@``, tab, CR).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings, get_settings
from app.domain.exceptions import NotFoundError, PermissionDeniedError
from app.domain.permissions import Permission, has_permission, require_permission
from app.domain.text import sanitize_excel_cell, sanitize_filename
from app.domain.timeutils import format_datetime
from app.models.audit_log import AuditAction
from app.models.user import User
from app.repositories.audit import AuditRepository
from app.repositories.procurements import ProcurementRepository
from app.repositories.purchase_requests import PurchaseRequestRepository

logger = logging.getLogger(__name__)

HEADER_FILL = PatternFill("solid", fgColor="DDE7F0")
HEADER_FONT = Font(bold=True)
TITLE_FONT = Font(bold=True, size=12)
THIN = Side(style="thin", color="9AA5B1")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
QUANTITY_FORMAT = "#,##0.###"
MAX_COLUMN_WIDTH = 60
MIN_COLUMN_WIDTH = 8


@dataclass(frozen=True, slots=True)
class ExcelFile:
    filename: str
    content: bytes

    @property
    def size(self) -> int:
        return len(self.content)


#: Column titles the import parser recognises; the template mirrors them so a
#: file filled in from the template always round-trips.
TEMPLATE_HEADERS = ("№", "Наименование", "Количество", "Ед. измерения", "Комментарий")
TEMPLATE_EXAMPLES: tuple[tuple[int, str, Decimal, str, str], ...] = (
    (1, "Сахар", Decimal("50"), "кг", ""),
    (2, "Масло", Decimal("5.5"), "л", "подсолнечное"),
    (3, "Яйца", Decimal("200"), "шт", ""),
)


def build_items_template() -> ExcelFile:
    """Blank list template a purchaser can fill in and send back."""
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.title = "Заявка"

    sheet.cell(row=1, column=1, value="Заполните таблицу и отправьте файл боту").font = (
        TITLE_FONT
    )
    sheet.cell(
        row=2,
        column=1,
        value="Строки с примерами можно удалить. Единицы: кг, л, шт, уп, пач, кор, м, м², м³…",
    )

    header_row = 4
    for column, title in enumerate(TEMPLATE_HEADERS, start=1):
        cell = sheet.cell(row=header_row, column=column, value=title)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.border = BORDER
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    for offset, example in enumerate(TEMPLATE_EXAMPLES, start=1):
        for column, value in enumerate(example, start=1):
            cell = sheet.cell(row=header_row + offset, column=column, value=value)
            cell.border = BORDER
            if column == 3:
                cell.number_format = QUANTITY_FORMAT

    sheet.freeze_panes = sheet.cell(row=header_row + 1, column=1)
    for column, width in enumerate((6, 40, 14, 16, 30), start=1):
        sheet.column_dimensions[get_column_letter(column)].width = width

    buffer = BytesIO()
    workbook.save(buffer)
    return ExcelFile(filename="Шаблон_заявки.xlsx", content=buffer.getvalue())


class ExcelExportService:
    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.requests = PurchaseRequestRepository(session)
        self.procurements = ProcurementRepository(session)
        self.audit = AuditRepository(session)

    # -- public API --------------------------------------------------------
    async def export_request(self, actor: User, request_id: int) -> ExcelFile:
        """Excel for a single purchase request (requirement 28)."""
        require_permission(actor, Permission.EXPORT_REQUEST)

        request = await self.requests.get_by_id(request_id)
        if request is None:
            raise NotFoundError("Заявка не найдена.")
        if not has_permission(actor, Permission.REQUEST_VIEW_ALL) and (
            request.purchaser_id != actor.id
        ):
            raise PermissionDeniedError("Это чужая заявка.")

        procurement = (
            await self.procurements.get_by_id(request.procurement_id)
            if request.procurement_id is not None
            else None
        )
        purchaser = await self.session.get(User, request.purchaser_id)
        if purchaser is None:  # pragma: no cover - FK guarantees
            raise NotFoundError("Данные заявки повреждены.")
        items = await self.requests.list_items(request.id)

        workbook = Workbook()
        sheet = workbook.active
        assert sheet is not None
        sheet.title = "Заявка"

        tz = self.settings.timezone
        created = request.submitted_at or request.created_at
        if procurement is not None:
            source_rows: list[tuple[str, object]] = [
                ("Закупка:", procurement.procurement_number),
                ("Название:", procurement.title),
            ]
        else:
            source_rows = [
                ("Закупка:", "Заявка по инициативе закупщика"),
                ("Тема:", request.subject or "—"),
            ]
        self._write_meta(
            sheet,
            [
                *source_rows,
                ("Заявка:", request.public_number),
                ("Закупщик:", purchaser.full_name),
                ("Дата:", format_datetime(created, tz)),
            ],
        )

        header_row = sheet.max_row + 2
        headers = ("№", "Наименование", "Количество", "Ед. измерения", "Комментарий")
        self._write_header(sheet, header_row, headers)

        row_index = header_row
        for item in items:
            row_index += 1
            self._write_row(
                sheet,
                row_index,
                [
                    item.position,
                    item.name,
                    item.quantity,
                    item.unit,
                    item.comment or "",
                ],
                numeric_columns={3},
            )

        if request.comment:
            row_index += 2
            sheet.cell(row=row_index, column=1, value="Комментарий к заявке:").font = HEADER_FONT
            sheet.cell(
                row=row_index, column=2, value=sanitize_excel_cell(request.comment)
            ).alignment = Alignment(wrap_text=True, vertical="top")

        sheet.freeze_panes = sheet.cell(row=header_row + 1, column=1)
        self._autofit(sheet)

        filename = self._request_filename(request.public_number, purchaser.full_name)
        content = self._to_bytes(workbook)

        self.audit.log(
            action=AuditAction.EXPORT_REQUEST_EXCEL,
            entity_type="purchase_request",
            entity_id=request.id,
            actor_user_id=actor.id,
            payload={"items": len(items)},
        )
        await self.session.commit()
        return ExcelFile(filename=filename, content=content)

    async def export_procurement(self, actor: User, procurement_id: int) -> ExcelFile:
        """Aggregate Excel: every request of a procurement plus a summary sheet."""
        require_permission(actor, Permission.EXPORT_PROCUREMENT)

        procurement = await self.procurements.get_by_id(procurement_id)
        if procurement is None:
            raise NotFoundError("Закупка не найдена.")

        rows = await self.requests.iter_procurement_items(procurement_id)
        summary = await self.requests.aggregate_items(procurement_id)
        tz = self.settings.timezone

        workbook = Workbook()
        detail = workbook.active
        assert detail is not None
        detail.title = "Заявки"

        self._write_meta(
            detail,
            [
                ("Закупка:", procurement.procurement_number),
                ("Название:", procurement.title),
                ("Срок подачи:", format_datetime(procurement.deadline, tz)),
                ("Заявок:", len({request.id for request, _item, _user in rows})),
                ("Позиций:", len(rows)),
            ],
        )

        header_row = detail.max_row + 2
        headers = (
            "№",
            "Закупщик",
            "Заявка",
            "Наименование",
            "Количество",
            "Ед.",
            "Комментарий",
        )
        self._write_header(detail, header_row, headers)

        row_index = header_row
        for counter, (request, item, purchaser) in enumerate(rows, start=1):
            row_index += 1
            self._write_row(
                detail,
                row_index,
                [
                    counter,
                    purchaser.full_name,
                    request.public_number,
                    item.name,
                    item.quantity,
                    item.unit,
                    item.comment or "",
                ],
                numeric_columns={5},
            )
        detail.freeze_panes = detail.cell(row=header_row + 1, column=1)
        self._autofit(detail)

        summary_sheet = workbook.create_sheet("Сводка")
        summary_sheet.cell(row=1, column=1, value="Сводка по закупке").font = TITLE_FONT
        summary_sheet.cell(
            row=2, column=1, value=sanitize_excel_cell(procurement.procurement_number)
        )
        note_row = 3
        summary_sheet.cell(
            row=note_row,
            column=1,
            value=(
                "Позиции объединены только при полном совпадении наименования и единицы "
                "измерения."
            ),
        )

        summary_header = note_row + 2
        self._write_header(
            summary_sheet, summary_header, ("Товар", "Ед.", "Общее количество", "Позиций")
        )
        summary_row = summary_header
        for name, unit, total, sources in summary:
            summary_row += 1
            self._write_row(
                summary_sheet,
                summary_row,
                [name, unit, total, sources],
                numeric_columns={3, 4},
            )
        summary_sheet.freeze_panes = summary_sheet.cell(row=summary_header + 1, column=1)
        self._autofit(summary_sheet)

        filename = sanitize_filename(f"{procurement.procurement_number}_сводный") + ".xlsx"
        content = self._to_bytes(workbook)

        self.audit.log(
            action=AuditAction.EXPORT_PROCUREMENT_EXCEL,
            entity_type="procurement",
            entity_id=procurement.id,
            actor_user_id=actor.id,
            payload={"rows": len(rows), "summary_rows": len(summary)},
        )
        await self.session.commit()
        logger.info(
            "aggregate excel generated",
            extra={
                "operation": "export_procurement",
                "user_id": actor.id,
                "procurement_id": procurement.id,
                "result": "ok",
            },
        )
        return ExcelFile(filename=filename, content=content)

    # -- helpers -----------------------------------------------------------
    @staticmethod
    def _request_filename(request_number: str, purchaser_name: str) -> str:
        base = sanitize_filename(f"{request_number}_{purchaser_name}")
        return f"{base}.xlsx"

    @staticmethod
    def _write_meta(sheet: Worksheet, pairs: list[tuple[str, object]]) -> None:
        for row, (label, value) in enumerate(pairs, start=1):
            sheet.cell(row=row, column=1, value=label).font = HEADER_FONT
            sheet.cell(row=row, column=2, value=sanitize_excel_cell(value))

    @staticmethod
    def _write_header(sheet: Worksheet, row: int, headers: tuple[str, ...]) -> None:
        for column, title in enumerate(headers, start=1):
            cell = sheet.cell(row=row, column=column, value=title)
            cell.font = HEADER_FONT
            cell.fill = HEADER_FILL
            cell.border = BORDER
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    @staticmethod
    def _write_row(
        sheet: Worksheet, row: int, values: list[object], numeric_columns: set[int]
    ) -> None:
        for column, value in enumerate(values, start=1):
            safe = value if column in numeric_columns else sanitize_excel_cell(value)
            cell = sheet.cell(row=row, column=column, value=safe)
            cell.border = BORDER
            if column in numeric_columns and isinstance(value, Decimal | int | float):
                cell.number_format = QUANTITY_FORMAT
                cell.alignment = Alignment(horizontal="right")
            else:
                cell.alignment = Alignment(vertical="top", wrap_text=False)

    @staticmethod
    def _autofit(sheet: Worksheet) -> None:
        widths: dict[int, int] = {}
        for row in sheet.iter_rows():
            for cell in row:
                if cell.value is None:
                    continue
                length = len(str(cell.value))
                widths[cell.column] = max(widths.get(cell.column, MIN_COLUMN_WIDTH), length + 2)
        for column, width in widths.items():
            sheet.column_dimensions[get_column_letter(column)].width = min(
                width, MAX_COLUMN_WIDTH
            )

    @staticmethod
    def _to_bytes(workbook: Workbook) -> bytes:
        buffer = BytesIO()
        workbook.save(buffer)
        return buffer.getvalue()
