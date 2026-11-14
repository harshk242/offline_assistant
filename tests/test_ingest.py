import sqlite3
from pathlib import Path

import pytest

from assistant.ingest import Line, RawPage, _clean, _render_table, assemble, ingest, printed_offset

MANUALS = Path(__file__).resolve().parent.parent / "manuals"


def test_clean_separates_section_numbers():
    assert _clean("10.1The motor does not run") == "10.1 The motor does not run"
    assert _clean("7.Starting up") == "7. Starting up"
    assert _clean("  P104   and P125 ") == "P104 and P125"


def test_grid_table_keeps_column_for_short_marks():
    rows = [["", "Daily", "Weekly"], ["Engine Oil Level", "C", ""], ["Fuel Filters", "", "R"]]
    assert _render_table(rows, has_header=True).splitlines()[1:] == [
        "Engine Oil Level | Daily: C", "Fuel Filters | Weekly: R"]


def test_merged_cells_inherit_value_above():
    rows = [["Fault", "Cause"], ["f.OF", "Output short circuit"], [None, "Acceleration time too short"]]
    assert _render_table(rows, has_header=True).splitlines()[-1] == "f.OF | Acceleration time too short"


def _page(n, lines):
    return RawPage(n, [Line(*ln) for ln in lines], 0)


def _add(page, *lines):
    page.lines += [Line(*ln) for ln in lines]


def test_heading_carries_over_and_footers_are_dropped():
    body, big = 7.0, 9.0
    raw = [_page(n, [(10, f"Book 123 page {n - 2}", body, False, True)]) for n in range(3, 8)]
    _add(raw[0], (100, "4. Starting up", big, True, False), (120, "Prime the pump.", body, False, False))
    _add(raw[1], (100, "Vent the pump.", body, False, False))
    _add(raw[2], (100, "Intro text", body, False, False), (120, "5. Maintenance", big, True, False))
    for p in raw[3:]:
        _add(p, (100, "More body text here.", body, False, False))
    pages = assemble(raw)
    assert [p.heading for p in pages[:3]] == ["4. Starting up", "4. Starting up", "4. Starting up"]
    assert pages[3].heading == "5. Maintenance"
    assert "Book" not in pages[0].text
    assert printed_offset(raw) == 2 and pages[0].printed_page == 1


@pytest.mark.skipif(not (MANUALS / "doosan_p250wjd_air_compressor.pdf").exists(), reason="sample manual missing")
def test_ingest_real_manual(tmp_path):
    pdf = MANUALS / "doosan_p250wjd_air_compressor.pdf"
    db = tmp_path / "index.db"
    assert ingest([pdf], db) == {pdf.stem: "indexed"}
    assert ingest([pdf], db) == {pdf.stem: "skipped"}
    c = sqlite3.connect(db)
    n_pages, offset = c.execute("SELECT n_pages, printed_offset FROM manuals").fetchone()
    assert (n_pages, offset) == (64, 2)
    page_id, page, printed, heading, text = c.execute(
        "SELECT page_id, page, printed_page, heading, text FROM pages WHERE page = 40").fetchone()
    assert page_id.endswith(":40") and printed == 38
    assert heading == "Compressor Diagnostic Display Codes"
    assert "5 | Low Eng Oil Press" in text
    assert c.execute("SELECT count(*) FROM pages").fetchone()[0] == 64
