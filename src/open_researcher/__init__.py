"""Compatibility shim for the legacy `open_researcher` package name."""

from importlib import import_module

_paperfarm = import_module("paperfarm")

__all__ = getattr(_paperfarm, "__all__", [])
__doc__ = getattr(_paperfarm, "__doc__", __doc__)
__file__ = getattr(_paperfarm, "__file__", __file__)
__path__ = list(getattr(_paperfarm, "__path__", []))
__version__ = getattr(_paperfarm, "__version__", "0.0.0")


def __getattr__(name: str):
    return getattr(_paperfarm, name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(dir(_paperfarm)))
