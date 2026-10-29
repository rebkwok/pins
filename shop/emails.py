"""
The shop's emails. Each is a list of blocks (paragraphs, lists, links), sent as
HTML (shop/emails/email.html: the logo, the blocks, and for customers the
footer from Shop settings) with a plain-text version made from the same blocks.

A block's text may contain HTML (e.g. <strong>, from format_html); the plain
text has the tags removed.
"""

import html
from dataclasses import dataclass, field

from django.conf import settings
from django.templatetags.static import static
from django.template.loader import render_to_string
from django.utils.html import conditional_escape, strip_tags
from django.utils.safestring import mark_safe


def _html(value):
    """A block's text as HTML: escaped unless it's already safe (format_html)"""
    return conditional_escape(value)


def _text(value):
    return html.unescape(strip_tags(str(_html(value))))


@dataclass
class Paragraph:
    """A paragraph; its lines (e.g. an address's) are kept"""

    content: str

    def as_text(self):
        return _text(self.content)

    def as_html(self):
        return mark_safe(_html(self.content).replace("\n", "<br>\n"))


@dataclass
class Items:
    """A list (e.g. of items), with an optional title ("Items:")"""

    lines: list
    title: str = ""

    def as_text(self):
        lines = [_text(self.title)] if self.title else []
        return "\n".join(lines + [f"- {_text(line)}" for line in self.lines])

    def as_html(self):
        return {"title": _html(self.title), "lines": [_html(line) for line in self.lines]}


@dataclass
class Link:
    label: str
    url: str

    def as_text(self):
        return f"{self.label}: {self.url}"


@dataclass
class Email:
    subject: str
    blocks: list = field(default_factory=list)
    # the footer from Shop settings (for emails to customers)
    footer: str = ""

    @property
    def text(self):
        text = "\n\n".join(block.as_text() for block in self.blocks)
        if self.footer:
            text += f"\n\n--\n{self.footer}"
        return text

    @property
    def html(self):
        return render_to_string(
            "shop/emails/email.html",
            {
                "subject": self.subject,
                "blocks": [
                    {"type": type(block).__name__.lower(), "block": block}
                    for block in self.blocks
                ],
                "footer": self.footer,
                "logo_url": logo_url(),
                "site_url": f"https://{settings.DOMAIN}",
            },
        )


def logo_url():
    """The site's logo, by its full address (for mail clients)"""
    url = static("images/logo.png")
    return url if url.startswith("http") else f"https://{settings.DOMAIN}{url}"
