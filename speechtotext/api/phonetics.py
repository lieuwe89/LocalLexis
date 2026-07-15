"""Double Metaphone encoding for fuzzy (phonetic) library search.

Segment text is indexed twice: verbatim (segments_fts) and with every word
replaced by its Double Metaphone primary code (segments_phonetic). A fuzzy
query encodes its tokens the same way, so "Catelin" matches "Kaitlyn".

The Python encoder and the frontend's npm `double-metaphone` never
cross-compare: the library path encodes query and index both server-side,
the in-transcript find encodes both client-side.
"""

from __future__ import annotations

import re

from metaphone import doublemetaphone

# Word tokenizer shared by the indexer and the phonetic snippet builder.
# Letters and digits only (no underscore), unicode-aware.
WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)


def encode_token(token: str) -> str:
    """Primary Double Metaphone code for one token.

    Tokens that produce no code (numbers, symbols) are returned lowercased
    verbatim so they still match exactly inside a phonetic query.
    """
    primary = doublemetaphone(token)[0]
    return primary if primary else token.lower()


def encode_text(text: str) -> str:
    """Replace each word in ``text`` with its phonetic code, space-joined.

    Token positions align 1:1 with WORD_RE matches over the original text;
    the snippet builder depends on that alignment.
    """
    return " ".join(encode_token(m.group(0)) for m in WORD_RE.finditer(text))
