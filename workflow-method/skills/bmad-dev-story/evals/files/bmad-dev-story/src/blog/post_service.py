"""PostService — depends only on the injected repository."""

from .post_repository import Post, PostRepository


class PostService:
    def __init__(self, repository: PostRepository):
        self._repository = repository

    def create_post(self, title: str, slug: str, body: str = "") -> Post:
        # TODO (story 3-1): reject duplicate slugs before persisting.
        post = Post(title=title, slug=slug, body=body)
        return self._repository.add(post)
