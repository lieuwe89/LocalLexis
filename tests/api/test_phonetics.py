"""Tests for the Double Metaphone token/text encoder used by fuzzy search."""

from __future__ import annotations

from speechtotext.api.phonetics import WORD_RE, encode_text, encode_token


def test_phonetic_pairs_share_code():
    # Classic ASR-mishearing pair: same pronunciation, different spelling.
    assert encode_token("Kaitlyn") == encode_token("Catelin")


def test_different_words_get_different_codes():
    assert encode_token("meeting") != encode_token("budget")


def test_unencodable_tokens_pass_through_lowercased():
    assert encode_token("2024") == "2024"
    assert encode_token("§§") == "§§"


def test_encode_text_replaces_each_word_with_its_code():
    out = encode_text("Hello world 42")
    assert out.split() == [encode_token("Hello"), encode_token("world"), "42"]


def test_encode_text_token_positions_align_with_word_re():
    # The snippet builder relies on 1:1 alignment between WORD_RE tokens
    # of the original text and the space-separated codes.
    text = "Well, Kaitlyn said: budget!"
    words = [m.group(0) for m in WORD_RE.finditer(text)]
    codes = encode_text(text).split()
    assert len(words) == len(codes)
