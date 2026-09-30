"""
Small server-drawn SVG charts for the web app (v2, phase 4, step 2). No JavaScript needed:
each bar carries a <title>, so hovering shows its date and count.
One series per chart in the accent colour, so no legend; each chart labels its own maximum.
"""
from markupsafe import Markup, escape


def daily_bars(values, labels, marker=None, marker_text="", width=600, height=64, pad_left=28):
    """values: counts; labels: one per bar (dates). marker: label where a dashed line is drawn."""
    n = len(values)
    top, bottom = 6, height - 14
    mx = max(max(values), 1)
    bw = (width - pad_left) / n
    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" preserveAspectRatio="none" '
             f'aria-label="{escape(", ".join(str(v) for v in values))}" class="bars">',
             f'<line x1="{pad_left}" x2="{width}" y1="{bottom}" y2="{bottom}" stroke="var(--rule)"/>',
             f'<text x="{pad_left - 4}" y="{top + 8}" text-anchor="end" class="ax">{mx}</text>',
             f'<text x="{pad_left - 4}" y="{bottom}" text-anchor="end" class="ax">0</text>']
    for i, (v, lab) in enumerate(zip(values, labels)):
        x = pad_left + i * bw
        h = (bottom - top) * v / mx
        parts.append(f'<g><title>{escape(lab)}: {v}</title>'
                     f'<rect x="{x:.1f}" y="{top}" width="{bw:.1f}" height="{bottom - top}" fill="transparent"/>'
                     + (f'<rect x="{x + 1:.1f}" y="{bottom - h:.1f}" width="{max(bw - 2, 1):.1f}" '
                        f'height="{h:.1f}" rx="1.5" fill="var(--accent)"/>' if v else '') + '</g>')
    for i, lab in enumerate(labels):
        if i % 7 == (n - 1) % 7:
            parts.append(f'<text x="{pad_left + i * bw + bw / 2:.1f}" y="{height - 2}" text-anchor="middle" '
                         f'class="ax">{escape(lab[5:])}</text>')
    if marker in labels:
        x = pad_left + labels.index(marker) * bw
        parts.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{top - 4}" y2="{bottom}" stroke="var(--warn)" '
                     f'stroke-dasharray="3 3"><title>{escape(marker_text)}</title></line>')
    parts.append("</svg>")
    return Markup("".join(parts))
