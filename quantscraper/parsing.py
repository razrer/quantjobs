"""Small parsing helpers for registries that publish web pages or spreadsheets."""

from __future__ import annotations

import html
import io
import re
import xml.etree.ElementTree as ElementTree
import zipfile
from html.parser import HTMLParser

_CELL_TAGS = ("td", "th")

_TAGS = re.compile(r"<[^>]+>")


def text(value: str | None, *, limit: int | None = None) -> str | None:
    """Readable text from a fragment of markup, or None if there is none.

    **Tags are stripped before entities are decoded, never after.** An employer
    who writes a literal `&lt;p&gt;` in their prose would otherwise have it
    decoded into a tag and then eaten.

    **And the decode itself was missing for a long time, in more than one
    place.** Every format that hands over HTML rather than JSON hands over its
    escaping too, so Coeli's `Operativ chef för Business &amp; Risk Operations`
    reached the tagger carrying the token `amp` -- a word in no lexicon, in the
    middle of a title, and the title is the first thing `tagging.py` reads.
    Nordic markup is worse than the ampersand: it spells `ä` as `&#xE4;`, so a
    title could fold to something no needle matches at all. It was fixed in one
    reader, then found again in a second and a third, which is why there is one
    definition here rather than a copy per reader.

    `limit` caps the result. `bodies` passes one: the tagger runs hundreds of
    patterns over a description, and one 400 KB posting stalls a worker pool
    through the GIL.
    """
    if not value:
        return None
    cleaned = " ".join(html.unescape(_TAGS.sub(" ", value)).split())
    return (cleaned[:limit] if limit else cleaned) or None


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


# An .xlsx is a zip of XML, so reading one needs no third-party library -- just
# enough of the format to get cell text out. AFM publishes its AIFM registers
# this way and nowhere else.
_SHEET_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_CELL_REF = re.compile(r"^([A-Z]+)")


def _column_index(reference: str) -> int:
    """`A1` -> 0, `C7` -> 2, `AA1` -> 26."""
    index = 0
    for character in _CELL_REF.match(reference).group(1):
        index = index * 26 + (ord(character) - ord("A") + 1)
    return index - 1


def xlsx_rows(body: bytes) -> list[list[str]]:
    """Rows of the first worksheet, as lists of cell text.

    Empty cells are omitted from the XML entirely, so cells are placed by their
    column reference rather than by order -- reading them in sequence silently
    shifts every value left of a gap into the wrong column.
    """
    archive = zipfile.ZipFile(io.BytesIO(body))

    shared: list[str] = []
    if "xl/sharedStrings.xml" in archive.namelist():
        shared = [
            "".join(item.itertext())
            for item in ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
        ]

    sheets = sorted(n for n in archive.namelist() if n.startswith("xl/worksheets/sheet"))
    if not sheets:
        raise ValueError("workbook contains no worksheet")
    data = ElementTree.fromstring(archive.read(sheets[0])).find(f"{_SHEET_NS}sheetData")

    rows = []
    for row in data if data is not None else []:
        cells: dict[int, str] = {}
        for cell in row:
            if cell.get("t") == "inlineStr":
                value = "".join(cell.itertext())
            else:
                element = cell.find(f"{_SHEET_NS}v")
                value = element.text or "" if element is not None else ""
                if cell.get("t") == "s" and value:
                    value = shared[int(value)]
            cells[_column_index(cell.get("r", "A1"))] = " ".join(value.split())
        width = max(cells, default=-1) + 1
        rows.append([cells.get(index, "") for index in range(width)])
    return rows
