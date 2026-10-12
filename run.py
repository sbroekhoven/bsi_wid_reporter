"""Entrypoint: uv run run.py [flags]"""

import sys

from bafin_wid_reporter.app import main

if __name__ == "__main__":
    sys.exit(main())
