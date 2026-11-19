"""Text helpers shared by the rule router, the wake-phrase matcher, and logging."""

from __future__ import annotations

import re
import sys


def safe_print(message: str) -> None:
    """Print that survives pythonw (no console) and non-UTF-8 Windows consoles."""
    stream = sys.stdout
    if not stream:
        return
    try:
        print(message, flush=True)
    except UnicodeEncodeError:
        encoding = getattr(stream, "encoding", None) or "ascii"
        print(message.encode(encoding, errors="replace").decode(encoding, errors="replace"), flush=True)
    except (OSError, ValueError):
        pass


def normalize(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s./:-]", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def plain_words(text: str) -> str:
    """Lowercase words only, all punctuation removed (for fuzzy comparisons, not for URLs or times)."""
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", text.lower())).strip()


def clean_transcript(text: str) -> str:
    """Drop sentence punctuation that Whisper adds ("Kecilkan volume." → "Kecilkan volume") while keeping
    dots inside tokens such as "kompas.com" or "19.30"."""
    text = re.sub(r"[.!?…]+(?=\s|$)", " ", text)
    text = re.sub(r"[,;:\"“”]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def contains_phrase(text: str, phrase: str) -> bool:
    """Whole-word match, so the alias "word" does not fire inside "password"."""
    if not phrase:
        return False
    return re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text) is not None


_URL_LIKE = re.compile(
    r"^(https?://)?[a-z0-9-]+(\.[a-z0-9-]+)*\.[a-z]{2,}(:\d+)?(/\S*)?$",
    re.IGNORECASE,
)


def looks_like_url(text: str) -> bool:
    return bool(_URL_LIKE.match(text.strip()))


_COMMAND_PREFIXES = [
    r"^(tolong\s+)?buka\s+(website|web|situs|file|folder|aplikasi|app|program)?\s*",
    r"^(tolong\s+)?cari\s+(file|folder|dokumen)?\s*",
    r"^(tolong\s+)?jalankan\s+(aplikasi|app|program)?\s*",
    r"^(tolong\s+)?open\s+",
]


def strip_command_words(text: str) -> str:
    result = normalize(text)
    for pattern in _COMMAND_PREFIXES:
        result = re.sub(pattern, "", result).strip()
    return result


_CONVERSATIONAL_REPLACEMENTS = {
    "bukain": "buka",
    "bukakan": "buka",
    "carikan": "cari",
    "cariin": "cari",
    "puterin": "putar",
    "putarkan": "putar",
    "nyalain": "buka",
    "matikanin": "matikan",
    # Jakarta slang and regional verb forms (Sundanese -keun, Javanese -no/-ke/-i). Bare "golek" is left alone:
    # it is also the puppet in "wayang golek".
    "nyariin": "cari", "nyari": "cari", "nyarikan": "cari", "carikin": "cari", "cariken": "cari", "carikeun": "cari",
    "golekno": "cari", "goleki": "cari", "golekke": "cari", "golekna": "cari", "golekin": "cari", "searchin": "cari",
    "liatin": "lihat", "lihatin": "lihat", "liat": "lihat", "ndelok": "lihat", "delok": "lihat", "lalajo": "nonton",
    "setelin": "setel", "setelkan": "setel", "nyetel": "setel", "nyetelin": "setel", "muterin": "putar", "puter": "putar",
    "bukak": "buka", "bukakno": "buka", "bukaen": "buka", "matiin": "matikan", "berhentiin": "hentikan",
    "lanjutin": "lanjutkan", "hapusin": "hapus", "bersihin": "bersihkan", "bersiin": "bersihkan",
    "kosongin": "kosongkan",
    # Site names as people type them or as speech-to-text writes them.
    "yutub": "youtube", "yutube": "youtube", "yutup": "youtube", "youtub": "youtube", "yt": "youtube",
    "gugel": "google", "gugle": "google",
}
_REPLACEMENT_WORDS = re.compile(
    r"\b(" + "|".join(sorted(map(re.escape, _CONVERSATIONAL_REPLACEMENTS), key=len, reverse=True)) + r")\b"
)
_SLANG_PATTERNS = [
    (r"\byou\s+tube\b", "youtube"),  # speech-to-text sometimes splits the name
    # Javanese/Sundanese "di" (nang, neng, ning, dina), only before a site name so song titles stay intact.
    (r"\b(?:nang|neng|ning|nok|nong|ing|dina)\s+(?=(?:youtube|google|spotify)\b)", "di "),
]

_SUBJECTS = r"(?:aku|gue|gua|gw|gwa|saya|ane|aing|abdi|kulo|kula|awak|sy|ak|aq)"
_WANTS = r"(?:mau|pengen|pengin|pingin|kepengen|kepingin|ingin|hayang|arep|mo|mw|pgn)"
_ACTIONS = (
    r"(?:cari|buka|nonton|tonton|putar|setel|play|lihat|cek|main|mainkan|dengerin|dengarkan|jalankan|open|search"
    r"|catat|catet|tulis|ingat|inget|ingatkan|ingetin|pasang|matikan|hentikan|lanjutkan|restart|kunci"
    r"|hapus|bersihkan|kosongkan)"
)
# Notes, reminders, and memories: after the polite layers are peeled, their words are stored as the user said them.
_CONTENT_HEAD = re.compile(r"^(?:catat|catet|catatlah|catetin|tulis|simpan|ingat|inget|ingatlah|ingatkan|ingetin|ingatin)\b")
_END_PARTICLES = r"(?:dong|donk|ya|yah|please|plis|pls|deh|sih|yuk|yok|ayo|ah|nih|gan|cuy|lah)"

# (pattern, replacement), applied until nothing changes, so "kak tolong dong cariin ... ya" peels layer by layer.
_CONVERSATIONAL_PATTERNS = [
    (r"^(?:zeta|mika|kak|kakak|bang|mas|mbak|mba|min|gan|sis|bro|yuk|yok|ayo|ayok|hayuk|hayu|dong|donk)\s+", ""),
    (r"^(?:tolong|tulung|coba|please|plis|pls|mohon|minta tolong|punten)\s+", ""),
    (r"^(aku\s+)?(mau|pengen|ingin)\s+", ""),
    # "gue mau nonton X" → "nonton X", but only before an action, so "gue mau tidur" still reads as small talk.
    (rf"^(?:{_SUBJECTS}\s+)?(?:(?:lagi|lg)\s+)?{_WANTS}\s+(?={_ACTIONS}\b)", ""),
    (r"^(bisa\s+(?:(?:nggak|ngga|gak|ga|enggak|engga)\s+)?)?(tolong\s+)?", ""),
    (r"^(\w+)\s+(?:dong|donk|deh|sih|yuk|yok|nih|lah)\s+(?=\S)", r"\1 "),  # "cari dong video X" → "cari video X"
    # Particles at the end only: names and person words can be content there ("ingatkan aku telepon kak",
    # "catat beli kado buat mika").
    (rf"\s+{_END_PARTICLES}$", ""),
]


def clean_conversational_command(command: str) -> str:
    """Turn casual or regional speech ("kak golekno video X nang yutub ya") into a command ("cari video X di youtube").
    Only the rule router sees this; the LLM still gets the user's own words."""
    command = normalize(command)
    command = re.sub(r"\.+(?=\s|$)", " ", command).strip()  # "di YouTube." typed with a full stop
    command = _peel(command)
    if _CONTENT_HEAD.match(command):
        return normalize(command)  # "catat liat jadwal" is saved as said, not as "lihat jadwal"
    command = _REPLACEMENT_WORDS.sub(lambda match: _CONVERSATIONAL_REPLACEMENTS[match.group(1)], command)
    for pattern, replacement in _SLANG_PATTERNS:
        command = re.sub(pattern, replacement, command)
    return normalize(_peel(command))  # peel again: "gue mau nyariin" only reads as "gue mau cari" after replacing


def _peel(command: str) -> str:
    """Remove polite and casual layers (vocatives, "tolong", "gue mau", particles) until nothing changes."""
    previous = None
    while previous != command:
        previous = command
        for pattern, replacement in _CONVERSATIONAL_PATTERNS:
            command = re.sub(pattern, replacement, command).strip()
    return command
