from __future__ import annotations

import pytest

from mika.memory import MemoryStore, as_spoken, sensitive_reason


def test_add_list_dedupe_and_reload(tmp_path):
    store = MemoryStore(tmp_path / "memory.json")
    store.add("aku suka kopi tanpa gula")
    store.add("Aku suka kopi tanpa gula.")  # same fact, different punctuation
    store.add("aku kerja shift malam", source="agent")
    assert [item.text for item in store.items()] == ["aku suka kopi tanpa gula", "aku kerja shift malam"]
    reloaded = MemoryStore(tmp_path / "memory.json")
    assert [(item.text, item.source) for item in reloaded.items()] == [("aku suka kopi tanpa gula", "voice"), ("aku kerja shift malam", "agent")]


@pytest.mark.parametrize(
    "fact",
    ["password wifi rumahku bandung123", "pin atm aku 1234", "nomor kartu kreditku 4111 1111 1111 1111", "nik aku 3201234567890001", "kode otp tadi 554433"],
)
def test_secrets_are_never_stored(tmp_path, fact):
    store = MemoryStore(tmp_path / "memory.json")
    assert sensitive_reason(fact)
    assert store.add(fact) is None and store.items() == []


def test_forget_by_keyword_and_clear(tmp_path):
    store = MemoryStore(tmp_path / "memory.json")
    store.add("aku suka kopi tanpa gula")
    store.add("aku alergi udang")
    assert [item.text for item in store.forget("soal kopi")] == ["aku suka kopi tanpa gula"]
    assert store.forget("teh hijau") == []
    assert store.clear() == 1 and store.items() == []


def test_relevant_prefers_matching_words(tmp_path):
    store = MemoryStore(tmp_path / "memory.json")
    for index in range(12):
        store.add(f"fakta acak nomor {index}")
    store.add("aku suka kopi tanpa gula")
    store.add("aku alergi udang")
    relevant = [item.text for item in store.relevant("tolong pesan kopi buat aku", limit=3)]
    assert relevant[0] == "aku suka kopi tanpa gula"
    assert len(relevant) == 3


def test_spoken_form_uses_second_person():
    assert as_spoken("aku suka kopi, saya juga suka teh") == "kamu suka kopi, kamu juga suka teh"


def test_corrupt_file_is_ignored(tmp_path):
    (tmp_path / "memory.json").write_text("not json", encoding="utf-8")
    assert MemoryStore(tmp_path / "memory.json").items() == []
