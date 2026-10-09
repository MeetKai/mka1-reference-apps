"""Convert model-generated HTML to a passive, self-contained report."""

from html import escape
from html.parser import HTMLParser

ALLOWED = {
    "h1",
    "h2",
    "h3",
    "h4",
    "p",
    "br",
    "hr",
    "strong",
    "b",
    "em",
    "i",
    "ul",
    "ol",
    "li",
    "table",
    "thead",
    "tbody",
    "tfoot",
    "tr",
    "th",
    "td",
    "caption",
    "pre",
    "code",
    "blockquote",
    "section",
    "div",
    "span",
    "main",
    "header",
    "footer",
    "small",
    "sup",
    "sub",
    "dl",
    "dt",
    "dd",
}
VOID = {"br", "hr"}
DISCARD = {"head", "script", "style", "iframe", "object", "svg", "math", "template"}


class PassiveHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.discard = []

    def handle_starttag(self, tag, attrs):
        if self.discard:
            if tag in DISCARD:
                self.discard.append(tag)
        elif tag in DISCARD:
            self.discard.append(tag)
        elif tag in ALLOWED:
            # No model-supplied attributes, CSS, URLs, or event handlers survive.
            self.parts.append(f"<{tag}>")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if self.discard:
            if tag == self.discard[-1]:
                self.discard.pop()
        elif tag in ALLOWED and tag not in VOID:
            self.parts.append(f"</{tag}>")

    def handle_data(self, data):
        if not self.discard:
            self.parts.append(escape(data))


def sanitize_report(source: str) -> bytes:
    parser = PassiveHTML()
    parser.feed(source)
    parser.close()
    body = "".join(parser.parts)
    if not body.strip():
        raise ValueError("The report contains no readable content.")
    return (
        """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>MKA1 CSV analysis report</title><style>
body{font:16px/1.65 system-ui,sans-serif;color:#17283a;max-width:1000px;margin:48px auto;padding:0 24px}
h1,h2,h3{line-height:1.2}h1{font-size:32px}h2{margin-top:36px;color:#147b71}
table{border-collapse:collapse;width:100%;margin:24px 0;display:block;overflow:auto}
th,td{border:1px solid #dbe2df;padding:10px 14px;text-align:left}th{background:#edf5f2}
pre,blockquote{padding:16px;background:#f4f6f5;overflow:auto}code{overflow-wrap:anywhere}
@media print{body{margin:0;max-width:none}table{display:table}}
</style></head><body>"""
        + body
        + "</body></html>"
    ).encode("utf-8")
