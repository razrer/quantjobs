"""Small parsing helpers for registries that publish web pages or spreadsheets."""

from __future__ import annotations

import html
import io
import re
import warnings
import xml.etree.ElementTree as ElementTree
import zipfile
from html.parser import HTMLParser

import bs4

# **A fetched page is never a locator, and saying so once is cheaper than
# reading the warning at 3am.** BeautifulSoup warns when the string it is
# given looks like a URL or a filename, on the theory that the caller meant
# to fetch it -- twelve lines of advice per occurrence. Every caller of
# `soup` below passes a body `http.get_text` already returned, so the
# premise cannot hold here; what it actually fires on is a broken host
# answering 200 with a bare redirect URL, which the readers handle by
# finding no postings. Filtered by class rather than globally, so a
# different warning from this library still reaches the transcript.
warnings.filterwarnings("ignore", category=bs4.MarkupResemblesLocatorWarning)

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


# How much fetched markup a reader will parse. A hostile or broken host can
# serve a gigabyte with an HTML content type, and building a tree from it would
# exhaust memory on a worker thread. Generous against what real boards serve --
# the largest here is the D. E. Shaw group's whole board on one page, at 869 KB.
#
# **Over the bound this raises rather than truncating**, which is the opposite
# of what `ats.py` and `pages.py` do with theirs, and the difference is what
# the caller does next. Those two are looking for a *signal* in a page and a
# clipped page can only cost them the signal; a reader here is enumerating a
# board, and a clipped page costs it postings it will then report as absent --
# principle 2 exactly, a scraper that breaks and returns fewer rows with
# HTTP 200. `extract._poll` turns this into a printed failure and writes
# nothing, so the board keeps the postings it already has.
MAX_MARKUP = 4_000_000


class MarkupTooLarge(ValueError):
    """The response is too large to parse. See `MAX_MARKUP` for why it raises."""


def soup(markup: str) -> bs4.BeautifulSoup:
    """Parse fetched markup once, the same way for every reader.

    **Why there is a parser here at all**, when this project's rule is that a
    library must replace something a hand-rolled block does worse. The board
    readers used to match markup with small stacks of bounded regexes, and
    `CLAUDE.md` records what that cost, one incident at a time:

      * `class="jv-job-list-location ml-auto"` -- a second class beside the one
        the pattern wanted, and every Jobvite location was lost, because the
        pattern required a quote where the markup has a space;
      * SuccessFactors and Jobvite each ship **two** list layouts, so each
        needed a second pattern written after a board answered HTTP 200 and
        read as empty -- the failure this project is least able to see;
      * SuccessFactors' `href` was captured verbatim and stored `&amp;` into
        849 live URLs, because a regex reads an attribute as bytes and a
        browser reads it as a decoded string.

    None of the three is reachable through a parser: a class is a member of a
    list, one selector matches both layouts, and an attribute is unescaped on
    the way out. That is the test the dependency rule asks for -- not that the
    library is shorter, though it is, but that it is *right* about the specific
    things the hand-rolled version was wrong about.

    `html.parser` rather than `lxml`: pure Python, so `weekly.ps1` keeps
    working after a bare `pip install -r requirements.txt` with no compiler in
    sight, and it is lenient about the malformed markup real boards serve.
    Measured over the ten captured board pages it is 8 MB/s -- about 20 ms for
    a typical page, against the 1-4 second throttled fetch that produced it, so
    the cost does not appear in any wall clock this project keeps.

    **`parsing.text` is still the way to read a node's prose**, not
    `get_text()`: the two agree on tags and entities and differ on the
    whitespace collapse, and one definition of that is the point of `text`.
    """
    if len(markup) > MAX_MARKUP:
        raise MarkupTooLarge(
            f"{len(markup):,d} bytes of markup, over the {MAX_MARKUP:,d} cap"
        )
    return bs4.BeautifulSoup(markup, "html.parser")


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
