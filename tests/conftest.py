import sqlite3

import pytest

from assistant.db import SCHEMA

PAGES = [
    ("pump", 35, "10.1 The motor does not run when started.",
     "Cause Remedy\nOne or more fuses are blown. Replace the fuses.\nThe motor-protective circuit breaker has tripped."),
    ("pump", 36, "10.6 The pump runs but gives no water.",
     "The foot or non-return valve is blocked in closed position.\nThere is leakage from the shaft seal."),
    ("vfd", 45, "5.3 Fault Messages",
     "f.OF | Output fault: Transistor fault | Output short circuit | Check motor/motor cable\n"
     "f.OF1 | Output fault: Ground fault | Grounded motor phase"),
    ("vfd", 46, "5.4 Alarms", "E-204 | Encoder signal lost | Check encoder wiring"),
    ("compressor", 40, "Compressor Diagnostic Display Codes",
     "5 | Low Eng Oil Press | SHUTDOWN condition due to low engine oil pressure."),
    ("compressor", 58, "Table 8: Low Engine Oil Pressure Shutdown SECU CODE 5",
     "Low oil level | Add oil.\nClogged oil filter | Replace filter."),
]


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.executescript(SCHEMA)
    c.executemany(
        "INSERT INTO pages (page_id, manual, page, printed_page, heading, text) VALUES (?, ?, ?, ?, ?, ?)",
        [(f"h:{p}", m, p, p, h, t) for m, p, h, t in PAGES])
    yield c
    c.close()
