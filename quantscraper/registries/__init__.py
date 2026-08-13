"""Registry plugins.

A registry is any module exposing:

    NAME          str   -- stable identifier, also the `source` column
    JURISDICTION  str   -- the *regulator's* jurisdiction, not the firm's
    MIN_EXPECTED  int   -- fewer rows than this is treated as a failed fetch
    fetch()             -- returns list[Employer]

`MIN_EXPECTED` is the whole silent-failure control: a scraper that breaks and
returns zero rows with HTTP 200 is far more dangerous than one that crashes,
because nothing announces it. Refusing to accept an implausibly small result
turns that into a visible error.
"""

from __future__ import annotations

from types import ModuleType

from . import afm_nl, cboe_europe, eurex, euronext, fi_se, fia_epta, sec_adv, sec_bd, seed

REGISTRIES: dict[str, ModuleType] = {
    module.NAME: module
    for module in (fi_se, afm_nl, sec_adv, sec_bd, fia_epta, eurex, euronext, cboe_europe, seed)
}
