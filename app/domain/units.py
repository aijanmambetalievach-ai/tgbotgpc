"""Unit-of-measure registry and normalisation.

The registry is intentionally data-driven: adding a new unit or a new
morphological alias means editing :data:`_UNIT_DEFINITIONS` (or calling
:func:`register_unit` at runtime) — no parser changes required.
"""

from __future__ import annotations

import re

#: canonical unit -> aliases (all lower-case, dots stripped)
_UNIT_DEFINITIONS: dict[str, tuple[str, ...]] = {
    "кг": ("кг", "килограмм", "килограмма", "килограммов", "килограммы", "кило"),
    "г": ("г", "гр", "грамм", "грамма", "граммов", "граммы"),
    "т": ("т", "тонна", "тонны", "тонн", "тоннаж"),
    "л": ("л", "литр", "литра", "литров", "литры"),
    "мл": ("мл", "миллилитр", "миллилитра", "миллилитров"),
    "шт": ("шт", "штука", "штуки", "штук", "штуке", "штучек", "штучка"),
    "м": ("м", "метр", "метра", "метров", "метры", "пм", "погонныйметр"),
    "м²": ("м²", "м2", "кв м", "квм", "квадратный метр", "квадратных метров", "кв.м"),
    "м³": ("м³", "м3", "куб м", "кубм", "кубический метр", "кубических метров", "куб.м"),
    "уп": ("уп", "упак", "упаковка", "упаковки", "упаковок", "упаковках"),
    "кор": ("кор", "короб", "коробка", "коробки", "коробок", "коробках"),
    "пач": ("пач", "пачка", "пачки", "пачек", "пачках"),
    "ящ": ("ящ", "ящик", "ящика", "ящиков", "ящики"),
    "меш": ("меш", "мешок", "мешка", "мешков", "мешки"),
    "рул": ("рул", "рулон", "рулона", "рулонов", "рулоны"),
    "компл": ("компл", "комп", "комплект", "комплекта", "комплектов", "комплекты", "набор",
              "набора", "наборов"),
    "бут": ("бут", "бутылка", "бутылки", "бутылок", "бутыль", "бутылях"),
    "кан": ("кан", "канистра", "канистры", "канистр"),
    "пар": ("пар", "пара", "пары"),
}

_ALIAS_TO_CANONICAL: dict[str, str] = {}


def _rebuild_index() -> None:
    _ALIAS_TO_CANONICAL.clear()
    for canonical, aliases in _UNIT_DEFINITIONS.items():
        _ALIAS_TO_CANONICAL[_clean(canonical)] = canonical
        for alias in aliases:
            _ALIAS_TO_CANONICAL[_clean(alias)] = canonical


def _clean(token: str) -> str:
    """Lower-case, strip dots/whitespace so that ``кв.м`` == ``кв м`` == ``квм``."""
    return re.sub(r"[.\s ]+", "", token.strip().lower()).replace("ё", "е")


def register_unit(canonical: str, aliases: tuple[str, ...] = ()) -> None:
    """Extension point: add a unit at runtime (e.g. from configuration)."""
    existing = _UNIT_DEFINITIONS.get(canonical, ())
    _UNIT_DEFINITIONS[canonical] = tuple(dict.fromkeys(existing + aliases))
    _rebuild_index()


def normalize_unit(token: str | None) -> str | None:
    """Return the canonical unit for ``token``, or ``None`` if unknown."""
    if not token:
        return None
    return _ALIAS_TO_CANONICAL.get(_clean(token))


def is_known_unit(token: str | None) -> bool:
    return normalize_unit(token) is not None


def known_aliases() -> list[str]:
    """All aliases, longest first — used to build parser regexes."""
    return sorted(_ALIAS_TO_CANONICAL, key=len, reverse=True)


def canonical_units() -> list[str]:
    return list(_UNIT_DEFINITIONS)


def raw_aliases() -> list[str]:
    """Every alias in its original spelling, longest first."""
    tokens: set[str] = set()
    for canonical, aliases in _UNIT_DEFINITIONS.items():
        tokens.add(canonical)
        tokens.update(aliases)
    return sorted(tokens, key=len, reverse=True)


def alias_pattern() -> str:
    """Regex alternation matching any unit alias, tolerant of dots and spaces."""
    parts = []
    for alias in raw_aliases():
        escaped = re.escape(alias)
        for literal in (r"\ ", " ", r"\.", "."):
            escaped = escaped.replace(literal, r"[\s.]*")
        parts.append(escaped)
    return "|".join(parts)


_rebuild_index()
