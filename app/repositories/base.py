"""Shared repository helpers."""

from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass(slots=True)
class Page[T]:
    """A single page of results plus the information needed to render pagers."""

    items: list[T] = field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 10

    @property
    def pages(self) -> int:
        if self.page_size <= 0:
            return 1
        return max(1, math.ceil(self.total / self.page_size))

    @property
    def has_prev(self) -> bool:
        return self.page > 1

    @property
    def has_next(self) -> bool:
        return self.page < self.pages

    @property
    def is_empty(self) -> bool:
        return not self.items


def normalize_page(page: int, page_size: int, total: int) -> int:
    """Clamp a requested page number into the valid range."""
    pages = max(1, math.ceil(total / page_size)) if page_size > 0 else 1
    return min(max(1, page), pages)


def offset_for(page: int, page_size: int) -> int:
    return max(0, (page - 1) * page_size)
