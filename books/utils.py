"""
Sanitize book content before it is ever saved to the database, so
uploaded/pasted HTML can never execute a stored-XSS attack when it is
later rendered inside the reader with the `|safe` filter.
"""
import bleach

ALLOWED_TAGS = ['p', 'br', 'strong', 'em', 'b', 'i', 'u', 'h1', 'h2', 'h3', 'h4', 'blockquote', 'ul', 'ol', 'li', 'span']
ALLOWED_ATTRS = {'span': ['class']}


def sanitize_book_content(raw_html: str) -> str:
    return bleach.clean(raw_html, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRS, strip=True)
