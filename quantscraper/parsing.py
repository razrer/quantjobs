"""Small HTML helpers for the registries that only publish web pages."""

from __future__ import annotations

from html.parser import HTMLParser

_CELL_TAGS = ("td", "th")


class _TableRowParser(HTMLParser):
    """Collects every <tr> in a document as a list of whitespace-collapsed cells."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "tr":
            self._row = []
        elif tag in _CELL_TAGS and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag in _CELL_TAGS and self._cell is not None and self._row is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)


def table_rows(html: str) -> list[list[str]]:
    """Every table row in `html`, as lists of cell text.

    Assumes tables are not nested, which holds for the registries we parse.
    """
    parser = _TableRowParser()
    parser.feed(html)
    return parser.rows
