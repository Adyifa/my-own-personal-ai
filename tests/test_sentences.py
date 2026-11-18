from __future__ import annotations

from mika.brain.sentences import HiddenTagFilter, SpeechSegmenter, clean_for_speech


def stream(segmenter: SpeechSegmenter, *chunks: str) -> list[list[str]]:
    """Feed chunks one by one and record what became speakable after each."""
    return [segmenter.feed(chunk) for chunk in chunks]


def test_sentences_are_released_as_soon_as_they_end():
    seg = SpeechSegmenter()
    emitted = stream(seg, "Halo! Aku Mi", "ka. Hari ini cer", "ah.")
    assert emitted == [["Halo!"], ["Aku Mika."], []]
    assert seg.flush() == ["Hari ini cerah."]


def test_numbers_domains_and_abbreviations_do_not_split():
    seg = SpeechSegmenter()
    out = seg.feed("Harganya Rp. 15.000 menurut kompas.com hari ini. Dr. Budi setuju. Oke ")
    assert out == ["Harganya Rp. 15.000 menurut kompas.com hari ini.", "Dr. Budi setuju."]
    assert seg.flush() == ["Oke"]


def test_last_sentence_waits_for_the_next_token():
    # "setuju." might still become "setuju.com"; only the next token tells.
    seg = SpeechSegmenter()
    assert seg.feed("Dr. Budi setuju.") == []
    assert seg.feed(" Lalu") == ["Dr. Budi setuju."]


def test_lowercase_after_period_is_not_a_new_sentence():
    seg = SpeechSegmenter()
    assert seg.feed("Ada sayur, buah, dll. juga minum. Selesai ") == ["Ada sayur, buah, dll. juga minum."]


def test_detail_marker_moves_rest_to_screen():
    seg = SpeechSegmenter()
    out = seg.feed("Ada tiga langkah utama. [DETAIL]\n1. Siapkan bahan\n2. Masak")
    assert out == ["Ada tiga langkah utama."]
    assert seg.feed(" 3. Sajikan") == []
    assert seg.flush() == []
    assert "1. Siapkan bahan" in seg.detail and "3. Sajikan" in seg.detail


def test_detail_marker_split_across_chunks():
    seg = SpeechSegmenter()
    spoken = []
    for chunk in ["Singkatnya begitu. [DE", "TAIL] rincian panjang"]:
        spoken += seg.feed(chunk)
    spoken += seg.flush()
    assert spoken == ["Singkatnya begitu."]
    assert seg.detail == "rincian panjang"


def test_sentence_budget_overflows_to_detail():
    seg = SpeechSegmenter(max_sentences=2)
    out = seg.feed("Satu. Dua. Tiga. Empat. ")
    out += seg.flush()
    assert out == ["Satu.", "Dua."]
    assert seg.overflowed
    assert seg.detail == "Tiga. Empat."


def test_long_first_sentence_splits_at_comma():
    seg = SpeechSegmenter(soft_limit=80)
    long_clause = "Menurut laporan terbaru dari beberapa media nasional hari ini, "
    out = seg.feed(long_clause + "harga beras naik sedikit di banyak kota besar")
    assert out == [long_clause.strip()]


def test_new_step_resets_budget_but_keeps_detail():
    seg = SpeechSegmenter(max_sentences=1)
    seg.feed("Bentar ya. Ini kelebihan. ")
    seg.flush()
    seg.new_step()
    assert seg.feed("Jawaban akhir.") + seg.flush() == ["Jawaban akhir."]
    assert "Ini kelebihan." in seg.detail


def test_think_block_is_hidden_even_when_split():
    tags = HiddenTagFilter()
    visible = "".join(tags.feed(chunk) for chunk in ["<thi", "nk>\nhmm, mikir dulu\n</th", "ink>\n\nHalo", " kamu"])
    visible += tags.flush()
    assert visible.strip() == "Halo kamu"


def test_tool_call_text_is_hidden():
    tags = HiddenTagFilter()
    visible = tags.feed('Oke. <tool_call>{"name": "open_app"}</tool_call> Siap.') + tags.flush()
    assert visible == "Oke.  Siap."


def test_unclosed_think_is_dropped_on_flush():
    tags = HiddenTagFilter()
    assert tags.feed("<think>belum selesai") == ""
    assert tags.flush() == ""


def test_clean_for_speech():
    assert clean_for_speech("**Menurut** [Kompas](https://kompas.com), harga naik 😊") == "Menurut Kompas, harga naik"
    assert clean_for_speech("- poin pertama") == "poin pertama"
    assert clean_for_speech("Cek https://x.com/a ya.") == "Cek ya."
    assert clean_for_speech("***") == ""
