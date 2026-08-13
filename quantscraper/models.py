"""The one record type every registry produces."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Employer:
    """A firm that could plausibly employ a quant.

    Deliberately thin: registries report what they know and nothing is
    inferred here. `category` is the registry's own classification, kept
    verbatim -- later layers use it to set polling frequency, never to
    decide membership.
    """

    source_id: str  # the registry's own key: org number, CRD number, slug
    name: str
    category: str | None = None
    city: str | None = None
    country: str | None = None
    website: str | None = None


@dataclass(frozen=True, slots=True)
class Job:
    """One posting, as the ATS published it.

    Deliberately thin and unclassified. Whether this is a quant role is a
    read-time question -- job titles are not comparable across firms ("Strat"
    at Goldman, "Trader" at Jane Street, "kvantitativ analytiker" in Stockholm)
    and a classifier that runs at write time cannot be re-run over history.
    """

    ats: str
    token: str
    job_id: str
    title: str
    url: str | None = None
    location: str | None = None
    department: str | None = None
    posted_at: str | None = None
    description: str | None = None
