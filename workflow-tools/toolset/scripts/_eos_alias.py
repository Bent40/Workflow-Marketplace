"""Pickle-safe alias for tokenizer.convert_tokens_to_ids.

On the box's stack (unsloth 2026.6.9 / trl 0.24 / transformers 5.5.0) unsloth's trl patch
injects bare placeholder strings (``<EOS_TOKEN>``, ``<PAD_TOKEN>``, ...) into
``SFTConfig``'s special-token fields, and trl validates each via
``convert_tokens_to_ids`` — a non-vocab placeholder is a hard ValueError. We make the
placeholders resolve by replacing ``tokenizer.convert_tokens_to_ids`` with the callable
below, which maps each known placeholder to a real vocab id and delegates everything else.

Why this lives in its own module instead of a closure in the __main__ training script:
trl's "Tokenizing" dataset map fans out through ``datasets`` + the ``multiprocess`` fork,
whose dill-based ``ForkingPickler`` serializes the tokenizer to each worker. A closure
defined in ``__main__`` is pickled *by value*, dragging the whole ``__main__`` namespace
(unsloth/torch objects, including an unpicklable ``ConfigModuleInstance``) into the pickle
and crashing the map. A class defined in this importable module pickles *by reference*
(just ``_eos_alias.TokenIdAlias`` + plain state), so the tokenizer serializes cleanly.
"""

from __future__ import annotations


class TokenIdAlias:
    """Callable drop-in for ``tokenizer.convert_tokens_to_ids`` that resolves unsloth's
    injected bare placeholders to real vocab ids and delegates all other lookups to the
    tokenizer's original implementation.

    Stores the *unbound* class implementation (importable, so it pickles by reference) plus
    the tokenizer instance, and calls ``impl(tokenizer, tokens)`` for non-aliased tokens —
    this deliberately avoids storing a *bound* method, whose default pickle reduction
    (``getattr(tokenizer, "convert_tokens_to_ids")``) would resolve back to this alias on a
    worker and recurse infinitely.
    """

    def __init__(self, tokenizer, alias_ids):
        self._tokenizer = tokenizer
        self._impl = type(tokenizer).convert_tokens_to_ids
        self._alias_ids = dict(alias_ids)

    def __call__(self, tokens):
        if isinstance(tokens, str) and tokens in self._alias_ids:
            return self._alias_ids[tokens]
        return self._impl(self._tokenizer, tokens)
