"""Template helpers for the monitoring screens.

The status badge lives here rather than being written inline in each template,
because UIUX_DESIGN §4.1 requires **icon + text + colour** on every status,
always. Centralising it means a template physically cannot render a status as
colour alone — which matters, since this product is built out of traffic lights
and red/green is the most common colour-vision deficiency.
"""

from django import template
from django.utils.html import format_html

register = template.Library()

# Shapes differ as well as hues, so the badges remain distinguishable in
# greyscale, in print, and under forced-colors.
BADGES = {
    "NONE": ("good", "✓", "No drift"),
    "MODERATE": ("warning", "▲", "Moderate"),
    "HIGH": ("critical", "✕", "High"),
    "INSUFFICIENT_DATA": ("muted", "–", "Not enough data"),
    "HEALTHY": ("good", "✓", "Healthy"),
    "WARNING": ("warning", "▲", "Warning"),
    "CRITICAL": ("critical", "✕", "Critical"),
    "INFO": ("muted", "i", "Info"),
    "ADVISED": ("warning", "▲", "Advised"),
    "URGENT": ("critical", "✕", "Urgent"),
    "NEW": ("critical", "●", "New"),
    "ACKNOWLEDGED": ("warning", "◐", "Acknowledged"),
    "RESOLVED": ("good", "✓", "Resolved"),
}


@register.simple_tag
def status_badge(value):
    if not value:
        return ""
    tone, icon, label = BADGES.get(str(value), ("muted", "–", str(value).title()))
    return format_html(
        '<span class="badge badge-{}" role="img" aria-label="{}">'
        '<span aria-hidden="true">{}</span> {}</span>',
        tone,
        label,
        icon,
        label,
    )


@register.filter
def pvalue(value):
    """Render p-values the way a statistician writes them."""
    if value is None:
        return "—"
    if value < 0.001:
        return "< 0.001"
    return f"{value:.3f}"


@register.filter
def test_label(value):
    return {"KS": "K-S", "CHI2": "Chi²"}.get(value, value or "—")


@register.filter
def pct(value, places=1):
    if value is None:
        return "—"
    return f"{value:.{places}f}%"
