"""Safe search helpers: bad input or a database hiccup must never produce a Django error page."""
import logging

from django.contrib import messages
from django.core.paginator import Paginator

logger = logging.getLogger('library')
MAX_QUERY_LENGTH = 100


def clean_text(value, max_length=MAX_QUERY_LENGTH):
    """Strip NUL bytes / surrounding space and cap the length."""
    return (value or '').replace('\x00', '').strip()[:max_length]


def clean_query(request, key='q'):
    return clean_text(request.GET.get(key, ''))


def safe_page(request, queryset, per_page):
    """Paginate AND evaluate the query inside try/except.

    Querysets are lazy, so database errors would otherwise surface later, while the template
    renders. Returns (page_obj, ok). On failure the technical error is logged server-side and the
    user gets an empty result plus a friendly message.
    """
    try:
        page_obj = Paginator(queryset, per_page).get_page(request.GET.get('page'))
        page_obj.object_list = list(page_obj.object_list)
        return page_obj, True
    except Exception:
        logger.exception("Search/list query failed for %s (user_id=%s)", request.path, getattr(request.user, 'pk', None))
        messages.error(request, "We couldn't complete that search right now. Please try again in a moment.")
        return Paginator([], per_page).get_page(1), False
