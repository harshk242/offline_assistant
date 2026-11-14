"""`python3 -m assistant "question"` (same as `ask`); `python3 -m assistant --ingest [paths]`."""

import sys

from .cli import ask_main, ingest_main

if len(sys.argv) > 1 and sys.argv[1] == "--ingest":
    sys.exit(ingest_main(sys.argv[2:]))
sys.exit(ask_main())
