"""Test package for Real-World Odds Oracle.

Importing this package puts the project's ``src/`` layout on ``sys.path`` so
``import rwoo...`` works under ``python3 -m unittest discover -s tests`` without
installing the package. This mirrors the bootstrap ``verify.py`` uses.
"""
import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_REPO_ROOT, "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)
