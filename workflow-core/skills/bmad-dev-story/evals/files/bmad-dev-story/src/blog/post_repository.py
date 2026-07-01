"""Single persistence path for posts. Do not add a second one."""


class Post:
    def __init__(self, title: str, slug: str, body: str = ""):
        self.title = title
        self.slug = slug
        self.body = body


class PostRepository:
    """In-memory stand-in for the real SQLAlchemy-backed repository."""

    def __init__(self):
        self._by_slug: dict[str, Post] = {}

    def slug_exists(self, slug: str) -> bool:
        # Case-insensitivity is enforced HERE, not in the service.
        return slug.lower() in self._by_slug

    def add(self, post: Post) -> Post:
        self._by_slug[post.slug.lower()] = post
        return post
