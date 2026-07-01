# Story 3-1 — Enforce unique post slugs

## Status

ready-for-dev

## Story

**As a** blog author,
**I want** the system to reject a post whose slug already exists,
**so that** two posts can never collide on the same public URL.

## Acceptance Criteria

1. Given a slug that no existing post uses, when `create_post` is called, then
   the post is persisted and returned with that slug.
2. Given a slug that an existing post already uses, when `create_post` is called,
   then it raises `DuplicateSlugError` and persists nothing.
3. Slug comparison is case-insensitive: `My-Post` collides with `my-post`.

## Tasks / Subtasks

- [ ] Add a `DuplicateSlugError` exception in `src/blog/errors.py` (AC: 2)
- [ ] In `PostService.create_post`, call `PostRepository.slug_exists(slug)` and
      raise `DuplicateSlugError` before persisting when it returns true (AC: 2, 3)
- [ ] Persist and return the post when the slug is free (AC: 1)
- [ ] Add unit tests covering the free-slug, duplicate-slug, and
      case-insensitive-collision paths (AC: 1, 2, 3)

## Dev Notes

- **Reuse, do not reinvent.** `PostRepository` (`src/blog/post_repository.py`)
  already exposes `slug_exists(slug: str) -> bool`, which lower-cases the slug
  before querying. Call it; do NOT write a second SQL query or add a new
  repository.
- **Case-insensitivity is the repository's job** — `PostService` must pass the
  raw slug straight through; do not pre-lowercase in the service.
- Services never touch the web layer or the ORM session directly; they depend on
  the injected repository only.
- [Source: architecture.md#Persistence] and [Source: architecture.md#Service layer]

## Dev Agent Record

### Debug Log

### Completion Notes

## File List

## Change Log
