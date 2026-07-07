"""Compatibility shim for the canonical Gold contract module.

New production code should import from ``apps.contracts.gold``.
"""

from apps.contracts.gold import *  # noqa: F401,F403
