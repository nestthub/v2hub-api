from __future__ import annotations

from importlib.metadata import PackageNotFoundError, metadata, version

try:
    __version__ = version("v2hub-api")
    __author__ = metadata("v2hub-api")["Author-email"]
except PackageNotFoundError:
    __version__ = "unknown"
    __author__ = "unknown"
