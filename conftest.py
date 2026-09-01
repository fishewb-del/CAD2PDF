"""
Put the project root on sys.path for the test suite.

Without this, `import app` / `import cad2pdf` only work if the project has
been pip-installed (e.g. `pip install -e .`). A fresh clone running plain
`pytest` would fail to collect, which is exactly what happened on CI.
pytest inserts the directory containing this conftest.py into sys.path, so
the tests run against the working tree as-is.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
