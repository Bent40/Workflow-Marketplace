"""Pagination helper for the API list endpoints."""


def paginate(items, page, page_size):
    """Return the slice of `items` for a 1-based `page` of size `page_size`.

    page=1 should return items[0:page_size],
    page=2 should return items[page_size:2*page_size], etc.
    """
    # BUG: treats `page` as 0-based when computing the start offset, so page=1
    # returns the SECOND page and page=0 would be needed to get the first page.
    start = page * page_size
    end = start + page_size
    return items[start:end]
