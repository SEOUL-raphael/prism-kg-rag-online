import re
from html.parser import HTMLParser

from .http_client import request_text
from .normalizer import html_to_text


class ElementByIdParser(HTMLParser):
    def __init__(self, target_id):
        HTMLParser.__init__(self, convert_charrefs=False)
        self.target_id = target_id
        self.depth = 0
        self.capturing = False
        self.parts = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if not self.capturing and attrs.get("id") == self.target_id:
            self.capturing = True
            self.depth = 1
            self.parts.append(self.get_starttag_text() or "")
            return
        if self.capturing:
            self.depth += 1
            self.parts.append(self.get_starttag_text() or "")

    def handle_startendtag(self, tag, attrs):
        if self.capturing:
            self.parts.append(self.get_starttag_text() or "")

    def handle_endtag(self, tag):
        if not self.capturing:
            return
        self.parts.append("</{0}>".format(tag))
        self.depth -= 1
        if self.depth <= 0:
            self.capturing = False

    def handle_data(self, data):
        if self.capturing:
            self.parts.append(data)

    def handle_entityref(self, name):
        if self.capturing:
            self.parts.append("&{0};".format(name))

    def handle_charref(self, name):
        if self.capturing:
            self.parts.append("&#{0};".format(name))


def extract_element_by_id(html, element_id):
    parser = ElementByIdParser(element_id)
    parser.feed(html or "")
    return "".join(parser.parts)


def extract_between(html, start_pattern, end_pattern=None):
    start = re.search(start_pattern, html or "", flags=re.I | re.S)
    if not start:
        return ""
    if not end_pattern:
        return html[start.start() :]
    end = re.search(end_pattern, html[start.end() :], flags=re.I | re.S)
    if not end:
        return html[start.start() :]
    return html[start.start() : start.end() + end.start()]


def extract_detail_body_from_html(html, rule):
    rule = rule or {}
    body_html = ""
    if rule.get("html_id"):
        body_html = extract_element_by_id(html, rule["html_id"])
    if not body_html and rule.get("start_pattern"):
        body_html = extract_between(html, rule["start_pattern"], rule.get("end_pattern"))
    text = html_to_text(body_html)
    for phrase in rule.get("stop_phrases", []):
        idx = text.find(phrase)
        if idx > 0:
            text = text[:idx].strip()
    return text


def fetch_detail_body(url, rule):
    if not url:
        return ""
    html, _, _ = request_text(url, timeout=int((rule or {}).get("timeout", 30)), retries=1)
    return extract_detail_body_from_html(html, rule)
