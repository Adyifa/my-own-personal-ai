"""Rule router: instant, offline handling of known commands; everything it is unsure about goes to the LLM."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from ..skills.power import POWER_LABELS
from ..text import contains_phrase, looks_like_url, normalize, strip_command_words


@dataclass
class Route:
    """Decision for one utterance: "rule" (run locally) or "agent" (ask the LLM), plus intent and arguments."""

    path: Literal["rule", "agent"]
    intent: str
    args: dict[str, Any] = field(default_factory=dict)


class Catalog(Protocol):
    """Names Mika can open; implemented by the Launcher."""

    def websites(self) -> dict[str, str]: ...

    def apps(self) -> dict[str, str]: ...

    def games(self) -> dict[str, str]: ...

    def file_aliases(self) -> dict[str, str]: ...


STOP_COMMANDS = {"keluar", "selesai", "berhenti", "stop", "exit", "quit"}
HELP_COMMANDS = {"bantuan", "help", "daftar perintah", "apa saja", "perintah apa saja"}
CONVERSATION_STOP = ["selesai ngobrol", "stop ngobrol", "udah dulu", "sudah dulu", "cukup ngobrol"]
OPEN_VERBS = {"buka", "open", "jalankan", "launch"}
GAME_VERBS = {"main", "mainkan", "game", "launch", "jalankan", "buka", "play"}
SEARCH_VERBS = ("cari", "search", "telusuri", "googling")
MUSIC_VERBS = ("putar", "mainkan", "play", "dengerin", "dengarkan", "setel")
FILE_WORDS = {"file", "folder", "dokumen"}
FILE_VERBS = {"buka", "cari", "open", "temukan", "tampilkan"}
_SKIP_ALIAS_PREFIXES = ("uninstall", "hapus instalasi", "remove", "readme", "help")

POWER_PHRASES = [
    ("shutdown", ["matikan laptop", "matikan komputer", "shutdown", "shut down"]),
    ("restart", ["restart laptop", "restart komputer", "mulai ulang"]),
    ("sleep", ["sleep laptop", "tidurkan laptop", "mode sleep", "sleep komputer"]),
    ("lock", ["kunci laptop", "lock laptop", "lock komputer"]),
    ("logout", ["logout", "log out", "keluar windows"]),
]

# Small talk categories. With an LLM these go to the agent; offline they pick a template reply.
CHAT_RULES: list[tuple[str, list[str], set[str]]] = [
    ("morning", ["selamat pagi"], {"pagi", "pagi mika"}),
    ("night", ["selamat malam", "mau tidur", "good night"], {"malam", "malam mika"}),
    ("greeting", [], {"halo", "hai", "hey", "hello", "helo", "halo mika", "hai mika"}),
    ("how_are_you", ["apa kabar", "kabar kamu", "gimana kabar", "lagi sehat"], set()),
    ("identity", ["siapa kamu", "kamu siapa", "nama kamu", "kenalin diri"], set()),
    ("thanks", ["makasih ya", "terima kasih ya"], {"makasih", "terima kasih", "thanks", "thank you"}),
    ("praise", ["kamu keren", "kamu pintar", "kamu pinter", "kamu lucu", "kamu imut", "mantap", "good job"], set()),
    ("apology", ["maaf ya", "sorry ya"], {"maaf", "sorry"}),
    ("bored", ["aku bosan", "aku bosen", "lagi bosan", "lagi bosen", "gabut"], set()),
    ("tired", ["aku capek", "aku cape", "aku lelah", "lagi capek", "ngantuk"], set()),
    ("sad", ["aku sedih", "lagi sedih", "aku galau", "kesepian", "sendirian"], set()),
    ("stress", ["aku stres", "aku stress", "lagi stres", "lagi stress", "overthinking", "cemas", "panik"], set()),
    ("chat_invite", ["ngobrol yuk", "temenin aku", "mika temenin", "aku mau curhat", "mau curhat", "curhat dong"], {"curhat"}),
    ("joke", ["cerita lucu", "joke", "lawak", "candaan"], set()),
    ("capabilities", ["kamu bisa apa", "bisa apa", "fitur kamu", "apa yang bisa kamu lakukan"], set()),
    ("status", ["lagi ngapain", "kamu lagi apa", "status kamu", "aktif nggak", "aktif gak"], set()),
]

SEARCH_REWRITES = [
    (r"^(nonton|tonton)\s+(youtube\s+)?(tentang\s+)?(.+)$", r"cari \4 di youtube"),
    (r"^lihat\s+(video\s+)?(.+)\s+di\s+youtube$", r"cari \2 di youtube"),
    (r"^(buka|putar|setel|play)\s+video\s+(.+?)(\s+di\s+youtube)?$", r"cari \2 di youtube"),
    (r"^(buka|putar)\s+(.+?)\s+di\s+youtube$", r"cari \2 di youtube"),
    (r"^youtube\s+(.+)$", r"cari \1 di youtube"),
    (r"^google\s+(.+)$", r"cari \1 di google"),
    (r"^googling\s+(.+)$", r"cari \1 di google"),
]
MUSIC_REWRITES = [
    (r"^lagu\s+(.+)$", r"putar lagu \1 di spotify"),
    (r"^putar\s+yang\s+(.+)$", r"putar lagu \1 di spotify"),
    (r"^putar\s+lagu\s+yang\s+(.+)$", r"putar lagu \1 di spotify"),
    (r"^musik\s+(.+)$", r"putar musik \1 di spotify"),
]
# Everyday skills (stage 2) ---------------------------------------------------------------
_EXPLAIN_START = re.compile(r"^(kenapa|mengapa|jelaskan|apa itu|apa bedanya|apa yang dimaksud|bagaimana cara|gimana cara)\b")
_CANCEL_WORDS = {"batalkan", "batal", "hapus", "stop", "matikan", "hentikan", "cancel", "buang"}
_REMIND_START = re.compile(r"^(?:tolong\s+)?(?:ingatkan|ingetin|ingatin|ingetkan|bangunkan|bangunin)\b")
_REMINDER_NOUNS = {"pengingat", "pengingatku", "reminder", "alarm"}
_LIST_CUES = ("apa saja", "apa aja", "daftar", "lihat", "cek", "ada pengingat", "ada apa", "pengingatku", "pengingat aku", "list")
_SNOOZE = re.compile(r"^(?:tunda|snooze)\b|^(?:ingatkan|ingetin|ingatin)\s+(?:aku\s+|saya\s+)?lagi(?:\s+(?:dalam\s+)?\S+\s+(?:menit|jam))?$")
_TIME_QUESTION = re.compile(r"\b(?:jam|pukul) berapa\b|^sekarang jam\b")
_DATE_QUESTION = re.compile(r"\btanggal berapa\b|\bhari apa\b|\btanggal hari ini\b|\bhari ini tanggal\b|^sekarang tanggal\b")
_RAIN_QUESTION = re.compile(r"\b(?:bakal|akan|mau|apakah|apa)\s+hujan\b|\bhujan\s+(?:nggak|gak|ga|enggak|tidak|ngga|kah|engga)\b")
_NOT_WEATHER = {"cpu", "laptop", "prosesor", "komputer", "processor", "gpu"}
MEDIA_COMMANDS = {
    "pause": ["pause", "jeda", "pause musik", "pause lagu", "pause lagunya", "pause dulu", "jeda musik", "jeda lagu",
              "jeda dulu", "hentikan musik", "hentikan lagu", "stop musik", "stop lagu", "stop lagunya"],
    "play": ["play", "resume", "lanjutkan musik", "lanjutkan lagu", "lanjutkan lagunya", "lanjut musik", "lanjut lagu",
             "putar lagi", "play lagi", "play musik", "putar musiknya lagi", "nyalakan musik lagi"],
    "next": ["next", "skip", "lagu berikutnya", "lagu selanjutnya", "lagu lain", "ganti lagu", "lewati lagu", "skip lagu",
             "skip lagu ini", "next lagu", "lagu sesudahnya"],
    "previous": ["previous", "prev", "lagu sebelumnya", "lagu tadi", "kembali ke lagu sebelumnya", "balik ke lagu sebelumnya"],
}
_MEDIA_LOOKUP = {phrase: action for action, phrases in MEDIA_COMMANDS.items() for phrase in phrases}
_VOLUME_VERBS = re.compile(
    r"\b(naik|naikkan|naikin|keraskan|kerasin|besarkan|besarin|gedein|tambah|tingkatkan|kencengin|turun|turunkan"
    r"|turunin|kecilkan|kecilin|pelankan|pelanin|kurangi|rendahkan|matikan|matiin|nyalakan|nyalain|hidupkan|bisukan"
    r"|aktifkan|bunyikan|diamkan)\b"
)
_BATTERY_WORDS = {"baterai", "batre", "batere", "baterei", "batrei", "battery"}
_CHARGING = re.compile(r"\b(?:lagi |sedang )?(?:dicas|di cas|ngecas|nge cas|dicharge|charging)\b")
_SYSTEM_PHRASES = ("info sistem", "informasi sistem", "status laptop", "status komputer", "kondisi laptop", "performa laptop",
                   "pemakaian cpu", "penggunaan cpu", "pemakaian ram", "penggunaan ram", "sisa disk", "sisa penyimpanan",
                   "ruang disk", "cpu", "ram", "penyimpanan")
_NOTE_ADD = re.compile(r"^(?:tolong\s+)?(?:catatlah|catat|catet|tulis catatan|simpan catatan|bikin catatan|buat catatan|tambah catatan|tambahkan catatan)\b")
_NOTE_READ = re.compile(
    r"^(?:(?:bacakan|baca|bacain|lihat|cek|apa|apa saja|daftar|sebutkan)\s+)?(?:isi\s+)?catatan(?:ku| aku| saya)?"
    r"(?:\s+(?:terakhir|terbaru|apa saja|aku|ku))?$"
)
_NOTE_OPEN = re.compile(r"^buka\s+(?:file\s+)?catatan(?:ku| aku| saya)?$")

_EXPLICIT_PROVIDER = re.compile(r"(?:^|\s)(?:di|ke|pake|pakai|lewat|via)\s+(google|youtube|yt)(?:\s|$)")
_FIRST_RESULT_PHRASES = ["nonton", "tonton", "buka video", "putar video", "hasil pertama"]


class Router:
    """Pure (decides, never acts), so routing accuracy can be tested without a mic or a model."""

    def __init__(self, config: dict[str, Any], catalog: Catalog):
        self.config = config
        self.catalog = catalog

    @property
    def plain_search_mode(self) -> str:
        """"answer": a plain "cari X" is answered by voice via the agent; "browser": open Google like before."""
        return normalize(str(self.config.get("search", {}).get("plain_search_mode", "answer"))) or "answer"

    def route(self, command: str) -> Route:
        """First confident rule wins; anything else goes to the agent (LLM)."""
        command = normalize(command)
        tokens = command.split()
        if not command:
            return Route("rule", "empty")
        if command in STOP_COMMANDS:
            return Route("rule", "stop")
        if command in HELP_COMMANDS or command.startswith("bantuan") or "daftar perintah" in command:
            return Route("rule", "help")
        if any(contains_phrase(command, phrase) for phrase in CONVERSATION_STOP):
            return Route("rule", "conversation_stop")
        if command in OPEN_VERBS:
            return Route("rule", "ask_target")

        for matcher in (
            self._match_power,
            self._match_everyday,
            self._match_music,
            self._match_file,
            self._match_search,
            self._match_named_target,
        ):
            route = matcher(command, tokens)
            if route is not None:
                return route

        category = classify_chat(command)
        if category:
            return Route("agent", "chat", {"category": category})
        if tokens[0] in OPEN_VERBS:
            return Route("agent", "open_unknown", {"target": strip_command_words(command)})
        return Route("agent", "general")

    # Matchers ---------------------------------------------------------------------------

    def _match_power(self, command: str, tokens: list[str]) -> Route | None:
        """Shutdown/restart/sleep/lock/logout (always confirmed by voice before running)."""
        for action, phrases in POWER_PHRASES:
            if any(contains_phrase(command, phrase) for phrase in phrases):
                return Route("rule", "power", {"action": action, "label": POWER_LABELS[action]})
        return None

    def _match_everyday(self, command: str, tokens: list[str]) -> Route | None:
        """Timers, reminders, time, weather, media, volume, battery, notes; "kenapa ..." questions go to the LLM."""
        if _EXPLAIN_START.search(command):
            return None
        words = set(tokens)

        if {"timer", "countdown"} & words or "hitung mundur" in command:
            if _CANCEL_WORDS & words:
                return Route("rule", "timer_cancel", {"text": command})
            if re.search(r"\b(sisa|berapa lagi|tinggal berapa|masih berapa|cek|status|berapa)\b", command):
                return Route("rule", "timer_status")
            return Route("rule", "timer_set", {"text": command})

        if _SNOOZE.search(command):
            return Route("rule", "snooze", {"text": command})
        remind_verb = bool(_REMIND_START.search(command))
        reminder_noun = bool(_REMINDER_NOUNS & words)
        if remind_verb or reminder_noun:
            if reminder_noun and _CANCEL_WORDS & words:
                return Route("rule", "reminder_cancel", {"text": command})
            if reminder_noun and not remind_verb and (command in _REMINDER_NOUNS or any(c in command for c in _LIST_CUES)):
                return Route("rule", "reminder_list")
            return Route("rule", "reminder_set", {"text": command})

        if _TIME_QUESTION.search(command):
            return Route("rule", "time_now")
        if _DATE_QUESTION.search(command):
            return Route("rule", "date_today")

        weather_word = bool({"cuaca", "prakiraan"} & words) or ("suhu" in words and not _NOT_WEATHER & words)
        if (weather_word or _RAIN_QUESTION.search(command)) and not explicit_provider(command):
            return Route("rule", "weather", {"text": command})

        if command in _MEDIA_LOOKUP:
            return Route("rule", "media", {"action": _MEDIA_LOOKUP[command]})
        if "volume" in words or command in {"mute", "unmute", "bisukan"} or ("suara" in words and _VOLUME_VERBS.search(command)):
            return Route("rule", "volume", {"text": command})

        if len(tokens) <= 6 and (_BATTERY_WORDS & words or _CHARGING.search(command)):
            return Route("rule", "system", {"kind": "battery"})
        if len(tokens) <= 6 and "suhu" not in words and any(contains_phrase(command, phrase) for phrase in _SYSTEM_PHRASES):
            return Route("rule", "system", {"kind": "system"})

        if _NOTE_OPEN.search(command):
            return Route("rule", "note_open")
        if _NOTE_ADD.search(command):
            return Route("rule", "note_add", {"text": command})
        if _NOTE_READ.search(command):
            return Route("rule", "note_read")
        return None

    def _match_music(self, command: str, tokens: list[str]) -> Route | None:
        """"putar lagu X" / "... di spotify" → Spotify search (videos and games excluded)."""
        if {"youtube", "video"} & set(tokens):
            return None
        rewritten = rewrite(command, MUSIC_REWRITES)
        if "spotify" not in rewritten.split() and not rewritten.startswith(tuple(f"{verb} " for verb in MUSIC_VERBS)):
            return None
        target = strip_command_words(rewritten)
        # "mainkan cs2" / "play valorant" are games, not songs.
        if self._is_game(clean_music_query(target)):
            return None

        query = target
        for alias, song_query in self.config.get("music", {}).get("songs", {}).items():
            alias_norm = normalize(alias)
            if alias_norm == target or contains_phrase(rewritten, alias_norm):
                query = song_query
                break
        query = clean_music_query(query)
        if not query:
            return Route("rule", "ask_music")
        return Route("rule", "music", {"query": query})

    def _match_file(self, command: str, tokens: list[str]) -> Route | None:
        """"buka/cari file|folder|dokumen X" → local file search."""
        if not (FILE_WORDS & set(tokens)):
            return None
        if tokens[0] not in FILE_VERBS and tokens[0] not in FILE_WORDS:
            return None
        rest = " ".join(tokens[1:])
        if rest in {normalize(alias) for alias in self.catalog.apps()}:
            return None  # "buka file explorer" is an app, not a file search
        return Route("rule", "open_file", {"query": strip_command_words(command), "command": command})

    def _match_search(self, command: str, tokens: list[str]) -> Route | None:
        """"cari X di google/youtube" opens the browser; a plain "cari X" is answered by the agent."""
        original = command
        command = rewrite(command, SEARCH_REWRITES)
        if not command.startswith(tuple(f"{verb} " for verb in SEARCH_VERBS)):
            return None
        provider = explicit_provider(command)
        query = clean_search_query(strip_command_words(command))
        if not query:
            return Route("rule", "ask_search_query")
        if provider is None:
            if self.plain_search_mode == "answer":
                return Route("agent", "web_answer", {"query": strip_info_words(query)})
            provider = normalize(str(self.config.get("search", {}).get("default_provider", "google"))) or "google"
        if provider == "youtube" and should_open_first_youtube_result(original):
            provider = "youtube_first"
        return Route("rule", "browser_search", {"provider": provider, "query": query})

    def _match_named_target(self, command: str, tokens: list[str]) -> Route | None:
        """Sites, games, apps, files matched together so the longest alias wins ("google chrome" beats "google")."""
        target = strip_command_words(command)
        game_target = strip_command_words(re.sub(r"^(main|mainkan|play|game)\s+", "", command))
        has_open_verb = tokens[0] in OPEN_VERBS
        catalogs = [
            ("open_website", self.catalog.websites(), has_open_verb, target),
            ("open_game", self.catalog.games(), bool(GAME_VERBS & set(tokens)), game_target),
            ("open_app", self.catalog.apps(), has_open_verb, target),
            ("open_file_alias", self.catalog.file_aliases(), has_open_verb, target),
        ]

        # 1. The whole target is an alias: works with or without a verb ("youtube", "main cs2").
        for intent, aliases, _, wanted in catalogs:
            for alias, value in aliases.items():
                if wanted and normalize(alias) == wanted:
                    return _named_route(intent, alias, value)

        # 2. With a verb, a whole-word alias inside the command; the longest alias wins.
        best: tuple[int, str, str, str] | None = None
        for intent, aliases, verb_ok, _ in catalogs:
            if not verb_ok:
                continue
            for alias, value in aliases.items():
                alias_norm = normalize(alias)
                if alias_norm and contains_phrase(command, alias_norm) and (best is None or len(alias_norm) > best[0]):
                    best = (len(alias_norm), intent, alias, value)
        if best is not None:
            return _named_route(best[1], best[2], best[3])

        # 3. A URL or "buka website X".
        if looks_like_url(target) and (has_open_verb or target == command):
            url = target if re.match(r"^https?://", target) else f"https://{target}"
            return Route("rule", "open_website", {"name": target, "url": url, "kind": "url"})
        if has_open_verb and {"website", "web", "situs"} & set(tokens) and target and " " not in target:
            return Route("rule", "open_website", {"name": target, "url": f"https://{target}", "kind": "url"})

        # 4. "buka chrome" -> the shortest app alias containing every spoken word ("google chrome").
        if has_open_verb and target:
            target_tokens = set(target.split())
            candidates = [
                (len(normalize(alias)), alias, value)
                for alias, value in self.catalog.apps().items()
                if target_tokens <= set(normalize(alias).split())
                and not normalize(alias).startswith(_SKIP_ALIAS_PREFIXES)
            ]
            if candidates:
                _, alias, value = min(candidates, key=lambda item: item[0])
                return _named_route("open_app", alias, value)
        return None

    def _is_game(self, name: str) -> bool:
        """True if the name is a known game (so "mainkan cs2" is not a song)."""
        name = normalize(name)
        return bool(name) and any(
            normalize(alias) == name or contains_phrase(name, normalize(alias)) for alias in self.catalog.games()
        )


# Pure helpers --------------------------------------------------------------------------


def _named_route(intent: str, alias: str, value: str) -> Route:
    """Build the Route for a matched alias."""
    if intent == "open_website":
        return Route("rule", intent, {"name": alias, "url": value, "kind": "alias"})
    if intent == "open_file_alias":
        return Route("rule", intent, {"name": alias, "path": value})
    return Route("rule", intent, {"name": alias, "target": value})


def classify_chat(command: str) -> str | None:
    """Small-talk category ("how_are_you", "tired", ...) for the offline template reply."""
    for category, phrases, exact in CHAT_RULES:
        if command in exact or any(contains_phrase(command, phrase) for phrase in phrases):
            return category
    return None


def rewrite(command: str, patterns: list[tuple[str, str]]) -> str:
    """Apply the first matching rewrite ("nonton X" → "cari X di youtube")."""
    for pattern, replacement in patterns:
        rewritten = re.sub(pattern, replacement, command).strip()
        if rewritten != command:
            return normalize(rewritten)
    return command


def explicit_provider(command: str) -> str | None:
    """"... di google" / "... di youtube" → that site; None when the user named no site."""
    match = _EXPLICIT_PROVIDER.search(command)
    if match:
        return "google" if match.group(1) == "google" else "youtube"
    return None


def should_open_first_youtube_result(command: str) -> bool:
    """"nonton X" / "putar video X" plays the top video instead of listing results."""
    if any(phrase in command for phrase in _FIRST_RESULT_PHRASES):
        return True
    return command.startswith(("buka ", "putar ", "setel ", "play ")) and "youtube" in command


def clean_search_query(query: str) -> str:
    """Strip "cari" and "di google/youtube" so only the search terms remain."""
    query = normalize(query)
    for pattern in [
        r"^(tolong\s+)?(cari|search|telusuri|googling)\s+",
        r"^(di\s+)?(google|youtube|yt)\s+",
        r"\s+(di|ke|pake|pakai|lewat|via)\s+(google|youtube|yt)$",
        r"\s+(google|youtube|yt)$",
    ]:
        query = re.sub(pattern, "", query).strip()
    return re.sub(r"\s+", " ", query).strip()


def strip_info_words(query: str) -> str:
    """"cari tahu tentang X" / "cari info X" -> "X"."""
    stripped = re.sub(r"^(tahu|info|informasi)\s+(tentang\s+|soal\s+|mengenai\s+)?", "", query).strip()
    return stripped or query


def clean_music_query(query: str) -> str:
    """Strip "putar lagu" and "di spotify" so only the song or artist remains."""
    query = normalize(query)
    for pattern in [
        r"^(tolong\s+)?(putar|mainkan|play|dengerin|dengarkan|setel)\s+",
        r"^lagu\s+",
        r"\s+(di|ke|pake|pakai)\s+spotify$",
        r"\s+spotify$",
    ]:
        query = re.sub(pattern, "", query).strip()
    query = query.replace(" dari ", " ").replace(" oleh ", " ")
    return re.sub(r"\s+", " ", query).strip()
