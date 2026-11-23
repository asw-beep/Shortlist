"""The digest email, as plain text and as HTML. Every value from a posting is escaped."""

from collections.abc import Callable, Mapping
from html import escape

from app.search.service import RankedJob

REASONS = {
    "skill": "matches your skills",
    "rrf": "close to your profile",
    "experience": "fits your experience",
    "location": "in a place you picked",
    "recency": "posted this week",
    "personal": "like jobs you saved",
}
ACTIONS = (("open", "Open"), ("save", "Save"), ("dismiss", "Not for me"))
REMOTE = {"remote_country": "Remote (India)", "remote_global": "Remote"}


def place(item: RankedJob) -> str:
    return item.city or REMOTE.get(item.remote_scope, "India")


def reasons(item: RankedJob, weights: Mapping[str, float] | None = None, top: int = 2) -> list[str]:
    """The factors that added most to the score, in words."""
    contribution = {
        name: value * (weights or {}).get(name, 1.0) for name, value in item.factors.items()
    }
    best = sorted(contribution, key=lambda name: -contribution[name])
    return [REASONS[name] for name in best if contribution[name] > 0][:top]


def render_digest(
    user_name: str,
    items: list[RankedJob],
    links: Callable[[RankedJob, str], str],
    *,
    weights: Mapping[str, float] | None = None,
    manage_url: str | None = None,
) -> tuple[str, str]:
    noun = "posting" if len(items) == 1 else "postings"
    intro = f"{len(items)} new {noun} that fit your profile this week:"
    footer = "You get this email because the weekly digest is on in your Shortlist profile."
    if manage_url:
        footer += f" Turn it off at {manage_url}"

    text_lines = [f"Hi {user_name},", "", intro, ""]
    html_items = []
    for number, item in enumerate(items, start=1):
        why = ", ".join(reasons(item, weights))
        text_lines += [f"{number}. {item.title} — {item.company} · {place(item)}"]
        if why:
            text_lines += [f"   Why: {why}"]
        text_lines += [f"   {label}: {links(item, action)}" for action, label in ACTIONS]
        text_lines += [""]
        anchors = " · ".join(
            f'<a href="{escape(links(item, action))}">{label}</a>' for action, label in ACTIONS
        )
        why_html = f"<br><small>{escape(why)}</small>" if why else ""
        html_items.append(
            f"<li><strong>{escape(item.title)}</strong> — {escape(item.company)} · "
            f"{escape(place(item))}{why_html}<br>{anchors}</li>"
        )
    text_lines += [footer]
    html = (
        f"<p>Hi {escape(user_name)},</p><p>{escape(intro)}</p>"
        f"<ol>{''.join(html_items)}</ol><p><small>{escape(footer)}</small></p>"
    )
    return "\n".join(text_lines), html
