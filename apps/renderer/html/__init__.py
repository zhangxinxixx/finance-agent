"""Standalone HTML renderers for read-only report artifacts."""

from apps.renderer.html.jin10_daily import render_jin10_daily_html
from apps.renderer.html.options_visual import render_options_visual_html

__all__ = ["render_options_visual_html", "render_jin10_daily_html"]
