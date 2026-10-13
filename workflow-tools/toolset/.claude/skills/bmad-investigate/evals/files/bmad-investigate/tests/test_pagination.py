from src.pagination import paginate

ITEMS = list(range(100))  # 0..99


def test_first_page_returns_first_chunk():
    # Expect page 1 to be items 0..9.
    assert paginate(ITEMS, page=1, page_size=10) == list(range(0, 10))


def test_second_page_returns_second_chunk():
    assert paginate(ITEMS, page=2, page_size=10) == list(range(10, 20))
