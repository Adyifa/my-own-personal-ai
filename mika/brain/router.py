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
CONVERSATION_STOP = ["selesai ngobrol", "stop ngobrol", "udah dulu", "sudah dulu", "cukup ngobrol", "udahan dulu", "udahan ya"]
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
    ("thanks", ["makasih ya", "terima kasih ya", "makasih banyak", "terima kasih banyak"], {"makasih", "terima kasih", "thanks", "thank you"}),
    ("praise", ["kamu keren", "kamu pintar", "kamu pinter", "kamu lucu", "kamu imut", "mantap", "good job"], set()),
    ("apology", ["maaf ya", "sorry ya"], {"maaf", "sorry"}),
    ("bored", ["aku bosan", "aku bosen", "lagi bosan", "lagi bosen", "gabut"], set()),
    ("tired", ["aku capek", "aku cape", "aku lelah", "lagi capek", "ngantuk"], set()),
    ("sad", ["aku sedih", "lagi sedih", "aku galau", "kesepian", "sendirian"], set()),
    ("stress", ["aku stres", "aku stress", "lagi stres", "lagi stress", "overthinking", "cemas", "panik"], set()),
    ("chat_invite", ["ngobrol yuk", "temenin aku", "mika temenin", "aku mau curhat", "mau curhat", "curhat dong"],
     {"curhat", "ngobrol", "temenin"}),  # the cleanup turns "ngobrol yuk" / "mika temenin" into one word
    ("joke", ["cerita lucu", "joke", "lawak", "candaan"], set()),
    ("capabilities", ["kamu bisa apa", "bisa apa", "fitur kamu", "apa yang bisa kamu lakukan"], set()),
    ("status", ["lagi ngapain", "kamu lagi apa", "status kamu", "aktif nggak", "aktif gak"], set()),
]

SEARCH_REWRITES = [
    # The optional tail keeps "nonton X di youtube" from becoming "cari X di youtube di youtube".
    (r"^(nonton|tonton)\s+(youtube\s+)?(tentang\s+)?(.+?)(\s+(di|ke|lewat|via)\s+youtube)?$", r"cari \4 di youtube"),
    (r"^(lihat|liat|cek|intip)\s+(video\s+)?(.+)\s+di\s+youtube$", r"cari \3 di youtube"),
    (r"^(buka|putar|setel|play)\s+video\s+(.+?)(\s+di\s+youtube)?$", r"cari \2 di youtube"),
    (r"^(buka|putar|setel|play|mainkan)\s+(.+?)\s+di\s+youtube$", r"cari \2 di youtube"),
    (r"^(buka|open)\s+youtube\s+(.+)$", r"cari \2 di youtube"),  # "bukain youtube smitty"
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
# Beyond Alexa (stage 4) ------------------------------------------------------------------
_SCREEN = re.compile(
    r"\b(?:lihat|liat|cek|baca|bacain|bacakan|jelaskan|terangkan|periksa)\s+(?:isi\s+)?"
    r"(?P<target>layar(?:ku| aku| saya)?|screen|jendela(?: ini)?|tampilan(?: layar)?)\b"
    r"|\bapa (?:yang )?(?:ada |tampil )?di layar(?:ku)?\b"
    r"|\b(?:baca|bacain|bacakan)\s+(?:tulisan|teks)\s+(?:yang ada\s+)?di\s+(?P<target2>layar(?:ku)?)\b"
)
_CLIPBOARD = re.compile(
    r"^(?:tolong\s+)?(?P<verb>rangkum|rangkumkan|ringkas|ringkaskan|terjemahkan|terjemahin|translate|artikan|jelaskan"
    r"|terangkan|bacakan|bacain|baca)\b.*?\b(?:clipboard|copy-?an|copyan|hasil copy(?:an)?"
    r"|(?:teks\s+)?yang\s+(?:(?:aku|ku|tadi|barusan|baru|saya)\s+){0,2}(?:copy|kopi|salin|dicopy|disalin|dikopi))\b"
)
_CLIPBOARD_ACTIONS = {
    "rangkum": "summarize", "rangkumkan": "summarize", "ringkas": "summarize", "ringkaskan": "summarize",
    "terjemahkan": "translate", "terjemahin": "translate", "translate": "translate", "artikan": "translate",
    "jelaskan": "explain", "terangkan": "explain", "bacakan": "read", "bacain": "read", "baca": "read",
}
_BRIEFING = re.compile(r"\b(?:briefing|brifing)\b|^(?:rangkuman|ringkasan) (?:hari ini|pagi)\b|^(?:apa )?agenda(?:ku| aku)? hari ini\b")
_NEWS = re.compile(
    r"^(?:(?:bacakan|baca|bacain|apa|ada)\s+)?(?:berita|headline)(?:\s+(?:utama|terbaru|terkini|penting))?"
    r"(?:\s+(?:hari ini|sekarang|pagi ini))?(?:\s+apa(?: saja| aja)?)?$"
)
_MEMORY_QUESTION = re.compile(r"^(?:kamu\s+)?(?:ingat|inget)\s+(?:nggak|gak|ga|tidak|enggak|apa|kah|ngga)\b")
_MEMORY_ADD = re.compile(
    r"^(?:kamu\s+)?(?:harus\s+)?(?:ingat(?:lah)?|inget(?:lah)?|ingat ingat)\s+(?:ya\s+)?(?:bahwa\s+|kalau\s+|kalo\s+)?(?P<fact>.+)$"
    r"|^(?:simpan|tambahkan|catat|masukkan)\s+(?:ini\s+)?(?:ke|di|dalam)\s+(?:memori|ingatan)(?:mu| kamu)?\s+(?:bahwa\s+)?(?P<fact2>.+)$"
)
_MEMORY_LIST = re.compile(
    r"\bapa (?:saja |aja )?yang kamu (?:ingat|inget|tahu|tau) tentang (?:aku|saya|diriku)\b"
    r"|\bkamu (?:ingat|inget|tahu|tau) apa (?:saja |aja )?tentang (?:aku|saya)\b"
    r"|\b(?:lihat|cek|daftar|isi) (?:memori|ingatan)(?:mu| kamu| mika)?\b"
    r"|^(?:memori|ingatan)(?:mu| kamu| mika)?(?: apa saja| apa aja)?$"
)
_MEMORY_FORGET = re.compile(
    r"^(?:lupakan|lupain|hapus (?:dari )?(?:memori|ingatan)(?:mu| kamu)?(?: tentang)?)"
    r"(?:\s+(?:bahwa|kalau|kalo|soal|tentang))?\s*(?P<what>.*)$"
)
_MEMORY_WIPE = re.compile(r"^(?:hapus|reset|kosongkan|bersihkan)\s+(?:semua\s+)?(?:memori|ingatan)(?:mu| kamu| mika)?(?:\s+tentang\s+(?:aku|saya))?$")

# Disk check and cache cleanup: a question about fullness → read-only report; "hapus cache ..." → cleanup that asks.
_DISK_NOUN = re.compile(r"\b(?:disk|disc|drive|hardisk|harddisk|hdd|ssd|penyimpanan|storage)\b")
_CLOUD_DRIVE = re.compile(r"\b(?:google drive|gdrive|onedrive|one drive)\b")
_DISK_FULL = re.compile(
    r"\b(?:penuh|kepenuhan|sesak|sempit|habis|tinggal (?:sedikit|dikit)|makan tempat|makan ruang|boros|penyebab\w*"
    r"|isi|isinya|paling besar|terbesar|gede banget|besar banget)\b"
)
_DISK_DEEP = re.compile(r"\b(?:detail|detil|lengkap|semua folder|menyeluruh|scan|analisis|analisa)\b")
_DISK_LOOK = re.compile(r"\b(?:cek|lihat|periksa|scan|analisis|analisa|ukur)\b")
_CLEAN_VERB = re.compile(r"^(?:hapus|bersihkan|kosongkan|clear|clean|cleanup|buang|delete)\b")
_CLEAN_TARGET = re.compile(
    r"\b(?:cache\w*|temp|temporary|file sementara|file sampah|junk|disk|disknya|penyimpanan|nvidia|shader|npm|pip"
    r"|crash dump|dump|windows update)\b"
)
_CLEAN_CATEGORIES = [
    (re.compile(r"\bnvidia\b"), "nvidia"),
    (re.compile(r"\bdirect ?x\b|\bd3d"), "directx"),
    (re.compile(r"\btemp\b|\btemporary\b|\bsementara\b"), "temp"),
    (re.compile(r"\bnpm\b"), "npm"),
    (re.compile(r"\bpip\b"), "pip"),
    (re.compile(r"\bcrash\b|\bdump\b"), "crash"),
    (re.compile(r"\bwindows update\b|\bupdate windows\b"), "windows_update"),
]
# Caches people ask about that are not on Mika's list (a browser's cache is the browser's own job).
_UNSUPPORTED_CACHE = re.compile(r"\b(chrome|edge|browser|firefox|opera|brave|discord|spotify|steam|whatsapp|telegram|zoom|teams)\b")
NEVER_MIND = {"saja", "aja", "aja deh", "deh", "ya", "saja deh", "lah", "dulu"}
FORGET_ALL = {"semua", "semuanya", "semua memori", "semua tentang aku", "semua yang kamu tahu", "semua yang kamu ingat",
              "semua ingatan", "semua memorimu"}

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
              "jeda dulu", "hentikan musik", "hentikan lagu", "stop musik", "stop lagu", "stop lagunya",
              "stop musiknya", "hentikan musiknya", "hentikan lagunya", "matikan musiknya", "matikan lagunya"],
    "play": ["play", "resume", "lanjutkan musik", "lanjutkan lagu", "lanjutkan lagunya", "lanjut musik", "lanjut lagu",
             "putar lagi", "play lagi", "play musik", "putar musiknya lagi", "nyalakan musik lagi", "lanjutkan musiknya",
             "lanjut lagunya"],
    "next": ["next", "skip", "lagu berikutnya", "lagu selanjutnya", "lagu lain", "ganti lagu", "lewati lagu", "skip lagu",
             "skip lagu ini", "next lagu", "lagu sesudahnya"],
    "previous": ["previous", "prev", "lagu sebelumnya", "lagu tadi", "kembali ke lagu sebelumnya", "balik ke lagu sebelumnya",
                 "balik ke lagu tadi", "kembali ke lagu tadi", "lagu yang tadi"],
}
_MEDIA_LOOKUP = {phrase: action for action, phrases in MEDIA_COMMANDS.items() for phrase in phrases}
_VOLUME_VERBS = re.compile(
    r"\b(naik|naikkan|naikin|keraskan|kerasin|besarkan|besarin|gedein|tambah|tingkatkan|kencengin|turun|turunkan"
    r"|turunin|kecilkan|kecilin|pelankan|pelanin|kurangi|rendahkan|matikan|matiin|nyalakan|nyalain|hidupkan|bisukan"
    r"|aktifkan|bunyikan|diamkan)\b"
)
# Verbs that only ever mean loudness ("kerasin dikit dong"), and "too loud/quiet" phrasing.
_VOLUME_ONLY_VERBS = {"kerasin", "keraskan", "kencengin", "kencangkan", "pelanin", "pelankan", "lirihkan"}
_LOUDNESS = re.compile(r"\b(?:kekecilan|kegedean|kebesaran|kekencengan|kekerasan|terlalu (?:keras|kenceng|kecil|pelan|besar)"
                       r"|kurang keras|kurang kenceng|nggak kedengeran|gak kedengeran)\b")
_BATTERY_WORDS = {"baterai", "batre", "batere", "baterei", "batrei", "battery", "baterainya", "batrenya", "baterenya"}
_CHARGING = re.compile(r"\b(?:lagi |sedang )?(?:dicas|di cas|ngecas|nge cas|dicharge|charging)\b")
_SYSTEM_PHRASES = ("info sistem", "informasi sistem", "status laptop", "status komputer", "kondisi laptop", "performa laptop",
                   "pemakaian cpu", "penggunaan cpu", "pemakaian ram", "penggunaan ram", "sisa disk", "sisa penyimpanan",
                   "ruang disk", "cpu", "ram", "penyimpanan")
_NOTE_ADD = re.compile(r"^(?:tolong\s+)?(?:catatlah|catat|catet|tulis catatan|simpan catatan|bikin catatan|buat catatan|tambah catatan|tambahkan catatan)\b")
_NOTE_READ = re.compile(
    r"^(?:(?:bacakan|baca|bacain|lihat|cek|apa|apa saja|daftar|sebutkan)\s+)?(?:isi\s+)?catatan(?:ku| aku| saya)?"
    r"(?:\s+(?:terakhir|terbaru|apa saja|apa aja|apa|aku|ku))?$"
)
_NOTE_OPEN = re.compile(r"^buka\s+(?:file\s+)?catatan(?:ku| aku| saya)?$")

# Safety ------------------------------------------------------------------------------------
# Self-harm statements get a fixed, careful reply (also offline), never a template or a web search.
_CRISIS = re.compile(
    r"\b(?:bunuh diri|mengakhiri hidup|ngakhirin hidup|akhiri hidup|nyakitin diri|menyakiti diri|melukai diri|self ?harm"
    r"|lebih baik aku mati|(?:nggak|gak|ga|tidak) mau hidup lagi|hidup(?:ku| aku| gue)? (?:nggak|gak|ga|tidak) ada gunanya)"
)
# Phrases that can also describe a device ("laptopku mau mati aja nih"): crisis only when no device is named.
_CRISIS_SOFT = re.compile(
    r"\b(?:pengen mati|ingin mati|pingin mati|mau mati aja|mending aku mati|mending aku (?:nggak|gak|ga) ada|capek hidup"
    r"|lelah hidup|pengen menghilang|ingin menghilang)"
    r"|^(?:aku|gue|gw|saya)\s+(?:udah|sudah)\s+(?:nggak|gak|ga|tidak)\s+kuat(?:\s+lagi)?$"
)
_DEVICE_WORDS = {"laptop", "laptopku", "hp", "hpku", "handphone", "baterai", "batre", "batere", "komputer", "pc", "lampu",
                 "tv", "mesin", "motor", "mobil", "aplikasi", "app", "wifi", "internet", "listrik", "server", "game", "kipas"}
# "jangan matikan laptop": a negated action is acknowledged, never executed.
_NEGATED = re.compile(r"^(?:jangan|gak usah|nggak usah|ga usah|enggak usah|tidak usah|gak jadi|nggak jadi|ga jadi"
                      r"|enggak jadi|tidak jadi|gak perlu|nggak perlu|tidak perlu)\s+(?P<rest>.+)$")
_ACTION_INTENTS = {"power", "disk_clean", "open_app", "open_game", "open_website", "open_file", "open_file_alias",
                   "browser_search", "music", "media", "volume", "timer_set", "timer_cancel", "reminder_set",
                   "reminder_cancel", "snooze", "note_add", "memory_add", "memory_forget", "memory_forget_all", "screen",
                   "clipboard"}
# Power commands that are really questions ("cara matikan laptop") or for later ("30 menit lagi") never shut down now.
_POWER_QUESTION = re.compile(r"^(?:cara|gimana|bagaimana|kenapa|mengapa|apa|apakah|kok|kapan|bisa nggak|bisakah)\b|\bcaranya\b")
_POWER_LATER = re.compile(r"\b(?:kalau|kalo|jika|setelah|sesudah|nanti|habis|abis|sebelum|tunggu|besok|malam ini)\b"
                          r"|\b(?:menit|jam|detik)\s+lagi\b|\b(?:sejam|semenit)\b|\bjam\s+\d")

_EXPLICIT_PROVIDER = re.compile(r"(?:^|\s)(?:di|ke|pake|pakai|lewat|via)\s+(google|youtube|yt)(?:\s|$)")
_OPEN_YOUTUBE_THEN = re.compile(r"^(?:buka|open)\s+youtube\s+(?:terus|trus|lalu|habis itu|abis itu|kemudian|dan)\s+(.+)$")
_BROWSER_HINT = re.compile(r"^(?:di|pake|pakai|lewat|via|ke|dengan|dalam)\b")
# Words after "buka youtube" / "nonton youtube" that are not a topic to search for.
_FILLER_WORDS = {"aja", "saja", "ajah", "sekarang", "skrg", "dulu", "lagi", "lg", "dong", "deh", "ya", "yah", "sebentar",
                 "bentar", "please", "plis", "yuk", "nih", "sih", "lah", "ah", "doang", "kembali", "mika",
                 "terus", "trus", "lalu", "kemudian", "dan", "tentang"}  # "buka youtube terus" trailing off
_MUSIC_WORDS = {"lagu", "lagunya", "musik", "musiknya", "playlist", "album", "podcast", "music", "song", "songs", "spotify"}
_BARE_MUSIC = {"lagu", "lagunya", "musik", "musiknya", "playlist", "music"}
# "youtube itu punya siapa" is a question about YouTube, not a search on it.
_ABOUT_YOUTUBE = re.compile(r"^(?:(?:buka|open)\s+)?youtube\s+(?:itu|tuh|ini|adalah|apa|siapa|kenapa|kok|gimana|bagaimana"
                            r"|berapa|kapan|punya|milik|bagus|jelek|error|down|lemot|nggak|gak|ga)\b")
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
        if is_crisis(command):
            return Route("rule", "crisis")
        negated = _NEGATED.match(command)
        if negated:
            inner = self.route(negated.group("rest"))
            if inner.path == "rule" and inner.intent in _ACTION_INTENTS:
                return Route("rule", "never_mind")  # "Oke." — and nothing happens
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
            self._match_beyond,
            self._match_disk,  # before everyday: "kenapa disk C-ku penuh" is about this laptop, not an explanation
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
                if _POWER_QUESTION.search(command):
                    return None  # "cara matikan laptop yang benar" is a question for the AI
                if _POWER_LATER.search(command):
                    return Route("rule", "power_later", {"action": action})  # scheduling is not supported yet
                return Route("rule", "power", {"action": action, "label": POWER_LABELS[action]})
        return None

    def _match_beyond(self, command: str, tokens: list[str]) -> Route | None:
        """Screen, clipboard, briefing, news headlines, and long-term memory commands."""
        screen = _SCREEN.search(command)
        if screen:
            question = re.sub(r"^(?:dong|ya|mika|deh)\b|\b(?:dong|ya|deh)$", "", (command[: screen.start()] + " " + command[screen.end() :]).strip()).strip()
            return Route("rule", "screen", {"question": question, "window": "jendela" in (screen.group("target") or "")})

        clip = _CLIPBOARD.search(command)
        if clip:
            from ..skills.clipboard import target_language

            return Route("rule", "clipboard", {"action": _CLIPBOARD_ACTIONS[clip.group("verb")], "language": target_language(command)})

        if _BRIEFING.search(command):
            return Route("rule", "briefing")
        if _NEWS.search(command):
            return Route("rule", "news")

        if _MEMORY_LIST.search(command):
            return Route("rule", "memory_list")
        if not _MEMORY_QUESTION.search(command):
            added = _MEMORY_ADD.search(command)
            if added:
                return Route("rule", "memory_add", {"fact": (added.group("fact") or added.group("fact2") or "").strip()})
        if _MEMORY_WIPE.search(command):
            return Route("rule", "memory_forget_all")
        forget = _MEMORY_FORGET.search(command)
        if forget:
            what = forget.group("what").strip()
            if what in NEVER_MIND:
                return Route("rule", "never_mind")
            if what in FORGET_ALL:
                return Route("rule", "memory_forget_all")
            return Route("rule", "memory_forget", {"what": what})
        return None

    def _match_disk(self, command: str, tokens: list[str]) -> Route | None:
        """"kenapa disk C-ku penuh?" → read-only report; "hapus cache nvidia" → cleanup that waits for "iya"."""
        if _CLEAN_VERB.search(command) and _CLEAN_TARGET.search(command):
            categories: list[str] = []
            for pattern, category in _CLEAN_CATEGORIES:
                if pattern.search(command) and category not in categories:
                    categories.append(category)
            if "shader" in tokens and not categories:
                categories = ["nvidia", "directx"]
            unsupported = _UNSUPPORTED_CACHE.search(command)
            if unsupported and not categories:
                return Route("rule", "disk_clean", {"categories": [], "unsupported": unsupported.group(1)})
            return Route("rule", "disk_clean", {"categories": categories})  # empty: every listed cache
        if not _DISK_NOUN.search(command) or _CLOUD_DRIVE.search(command):
            return None
        if _DISK_FULL.search(command):
            return Route("rule", "disk_report", {"deep": bool(_DISK_DEEP.search(command))})
        if _DISK_DEEP.search(command) and _DISK_LOOK.search(command):
            return Route("rule", "disk_report", {"deep": True})  # "cek detail disk", "scan disk c"
        return None

    def _match_everyday(self, command: str, tokens: list[str]) -> Route | None:
        """Timers, reminders, time, weather, media, volume, battery, notes; "kenapa ..." questions go to the LLM."""
        if _EXPLAIN_START.search(command):
            return None
        words = set(tokens)

        if {"timer", "timernya", "countdown"} & words or "hitung mundur" in command:
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

        weather_word = (
            bool({"cuaca", "cuacanya", "prakiraan", "payung", "cerah", "mendung", "gerimis", "berawan"} & words)
            or (bool({"suhu", "derajat"} & words) and not _NOT_WEATHER & words)
            or ("panas" in words and "luar" in words)
        )
        if (weather_word or _RAIN_QUESTION.search(command)) and not explicit_provider(command):
            return Route("rule", "weather", {"text": command})

        if command in _MEDIA_LOOKUP:
            return Route("rule", "media", {"action": _MEDIA_LOOKUP[command]})
        loudness = {"suara", "suaranya"} & words and (_VOLUME_VERBS.search(command) or _LOUDNESS.search(command))
        if "volume" in words or command in {"mute", "unmute", "bisukan"} or loudness or tokens[0] in _VOLUME_ONLY_VERBS:
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
        starts_with_verb = rewritten.startswith(tuple(f"{verb} " for verb in MUSIC_VERBS))
        on_spotify = re.search(r"\b(?:di|ke|pake|pakai|lewat|via)\s+spotify\b", rewritten)
        opens_spotify = re.fullmatch(r"(?:(?:buka|open|jalankan|putar|mainkan|play)\s+)?(?:aplikasi\s+)?spotify", rewritten)
        if not (starts_with_verb or on_spotify or opens_spotify):
            return None  # "spotify bagus nggak" is a question, not a song request
        music_words = _MUSIC_WORDS & set(rewritten.split())
        if not music_words and not opens_spotify:
            if rewritten.startswith(("mainkan ", "play ")) and not self._is_song_alias(rewritten):
                return None  # "mainkan valorant": a game or app, let the next matchers or the AI decide
            if self._starts_with_app(clean_music_query(strip_command_words(rewritten))):
                return None  # "putar netflix film horor" is about Netflix, not a Spotify search
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
        if query in _BARE_MUSIC:
            return Route("rule", "ask_music")  # "putar lagu" names no song
        if query == "spotify":
            return self._open_spotify()  # "buka spotify" opens Spotify itself, not a search for the word "spotify"
        if not query:
            return Route("rule", "ask_music")
        return Route("rule", "music", {"query": query})

    def _open_spotify(self) -> Route:
        """The installed Spotify app (Store or desktop), else a "spotify" website alias, else the web player."""
        found = self._first_alias("spotify", (("open_app", self.catalog.apps), ("open_website", self.catalog.websites)))
        return found or Route("rule", "open_website", {"name": "spotify", "url": "https://open.spotify.com", "kind": "url"})

    def _youtube_home(self) -> Route:
        """The "youtube" website alias, else youtube.com."""
        found = self._first_alias("youtube", (("open_website", self.catalog.websites),))
        return found or Route("rule", "open_website", {"name": "youtube", "url": "https://www.youtube.com", "kind": "url"})

    def _first_alias(self, name: str, sources) -> Route | None:
        """Route to the first catalog entry named exactly `name`; catalogs are read in order and only when needed."""
        for intent, aliases in sources:
            for alias, value in aliases().items():
                if normalize(alias) == name:
                    return _named_route(intent, alias, value)
        return None

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
        compound = _OPEN_YOUTUBE_THEN.match(command)
        if compound:
            command = f"{compound.group(1)} di youtube"  # "buka youtube terus cari smitty" → "cari smitty di youtube"
        original = command
        if _ABOUT_YOUTUBE.match(command):
            return None
        opened = re.sub(r"^(buka|open)\s+", "", command)
        if opened.startswith("youtube "):
            rest = opened[len("youtube "):]
            # "buka youtube music" is a site or app of its own; "buka youtube di chrome" names a browser, not a topic.
            if _BROWSER_HINT.match(rest) or self._is_known_name(opened):
                return None
        command = rewrite(command, SEARCH_REWRITES)
        if not command.startswith(tuple(f"{verb} " for verb in SEARCH_VERBS)):
            return None
        provider = explicit_provider(command)
        query = clean_search_query(strip_command_words(command))
        if provider == "youtube" and set(query.split()) <= _FILLER_WORDS:
            query = ""  # "buka youtube aja", "nonton youtube sekarang"
        if not query:
            if provider == "youtube" and not original.startswith(tuple(f"{verb} " for verb in SEARCH_VERBS)):
                return self._youtube_home()  # "nonton youtube" without a topic opens YouTube itself
            return Route("rule", "ask_search_query")
        if provider is None:
            if self.plain_search_mode == "answer":
                return Route("agent", "web_answer", {"query": strip_info_words(query)})
            provider = normalize(str(self.config.get("search", {}).get("default_provider", "google"))) or "google"
        if provider == "youtube":
            query = re.sub(r"^(video|vidio|videonya)\s+(?!klip\b|clip\b)", "", query)  # all of YouTube is video
            if should_open_first_youtube_result(original):
                provider = "youtube_first"
        return Route("rule", "browser_search", {"provider": provider, "query": query})

    def _match_named_target(self, command: str, tokens: list[str]) -> Route | None:
        """Sites, games, apps, files matched together so the longest alias wins ("google chrome" beats "google")."""
        target = strip_command_words(command)
        game_target = strip_command_words(re.sub(r"^(main|mainkan|play|game)\s+", "", command))
        has_open_verb = tokens[0] in OPEN_VERBS
        sources = {
            "open_website": self.catalog.websites,
            "open_game": self.catalog.games,
            "open_app": self.catalog.apps,
            "open_file_alias": self.catalog.file_aliases,
        }
        loaded: dict[str, dict[str, str]] = {}

        def aliases_of(intent: str) -> dict[str, str]:
            # Read on first use: "buka youtube" matches a website without waiting for app discovery to finish.
            if intent not in loaded:
                loaded[intent] = sources[intent]()
            return loaded[intent]

        catalogs = [
            ("open_website", has_open_verb, target),
            ("open_game", bool(GAME_VERBS & set(tokens)), game_target),
            ("open_app", has_open_verb, target),
            ("open_file_alias", has_open_verb, target),
        ]

        # 1. The whole target is an alias: works with or without a verb ("youtube", "main cs2").
        for intent, _, wanted in catalogs:
            if not wanted:
                continue
            for alias, value in aliases_of(intent).items():
                if normalize(alias) == wanted:
                    return _named_route(intent, alias, value)

        # 2. With a verb, a whole-word alias inside the command; the longest alias wins.
        best: tuple[int, str, str, str] | None = None
        for intent, verb_ok, _ in catalogs:
            if not verb_ok:
                continue
            for alias, value in aliases_of(intent).items():
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

        # 4a. "main dota" -> the shortest game alias containing every spoken word ("dota 2").
        if GAME_VERBS & set(tokens) and game_target:
            wanted = set(game_target.split())
            games = [
                (len(normalize(alias)), alias, value)
                for alias, value in aliases_of("open_game").items()
                if wanted <= set(normalize(alias).split())
            ]
            if games:
                _, alias, value = min(games, key=lambda item: item[0])
                return _named_route("open_game", alias, value)

        # 4b. "buka chrome" -> the shortest app alias containing every spoken word ("google chrome").
        if has_open_verb and target:
            target_tokens = set(target.split())
            candidates = [
                (len(normalize(alias)), alias, value)
                for alias, value in aliases_of("open_app").items()
                if target_tokens <= set(normalize(alias).split())
                and not normalize(alias).startswith(_SKIP_ALIAS_PREFIXES)
            ]
            if candidates:
                _, alias, value = min(candidates, key=lambda item: item[0])
                return _named_route("open_app", alias, value)
        return None

    def _is_known_name(self, name: str) -> bool:
        """True if the whole phrase is a site, app, or game alias. Catalogs are read lazily, websites first."""
        sources = (self.catalog.websites, self.catalog.apps, self.catalog.games)
        return any(normalize(alias) == name for source in sources for alias in source())

    def _is_game(self, name: str) -> bool:
        """True if the name is a known game, also partly ("mainkan apex" → Apex Legends), so it is not a song."""
        name = normalize(name)
        wanted = set(name.split())
        return bool(name) and any(
            normalize(alias) == name or contains_phrase(name, normalize(alias)) or wanted <= set(normalize(alias).split())
            for alias in self.catalog.games()
        )

    def _is_song_alias(self, command: str) -> bool:
        return any(contains_phrase(command, normalize(alias)) for alias in self.config.get("music", {}).get("songs", {}))

    def _starts_with_app(self, query: str) -> bool:
        """"netflix film horor" starts with an installed app's name (Spotify itself excluded)."""
        return any(
            len(alias) >= 3 and alias != "spotify" and (query == alias or query.startswith(alias + " "))
            for alias in (normalize(name) for name in self.catalog.apps())
        )


# Pure helpers --------------------------------------------------------------------------


def is_crisis(command: str) -> bool:
    """Self-harm statements ("aku pengen mati aja"), checked before anything else."""
    command = normalize(command)
    if _CRISIS.search(command):
        return True
    return bool(_CRISIS_SOFT.search(command)) and not _DEVICE_WORDS & set(command.split())


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
    return command.startswith(("buka ", "putar ", "setel ", "play ", "mainkan ")) and "youtube" in command


def clean_search_query(query: str) -> str:
    """Strip "cari" and "di google/youtube" so only the search terms remain."""
    query = normalize(query)
    previous = None
    while previous != query:  # repeated, so a doubled "di youtube di youtube" leaves nothing behind
        previous = query
        for pattern in [
            r"^(tolong\s+)?(cari|search|telusuri|googling)\s+",
            r"^(di\s+)?(google|youtube|yt)\s+",
            r"\s+(di|ke|pake|pakai|lewat|via)\s+(google|youtube|yt)$",
            r"\s+(google|youtube|yt)$",
        ]:
            query = re.sub(pattern, "", query).strip()
    query = re.sub(r"\s+", " ", query).strip()
    return "" if query in {"di", "ke", "pake", "pakai", "lewat", "via"} else query  # "nonton youtube" has no query


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
        r"^(?:dari|oleh|punya)\s+",
        r"\s+(di|ke|pake|pakai)\s+spotify$",
        r"\s+spotify$",
    ]:
        query = re.sub(pattern, "", query).strip()
    query = query.replace(" dari ", " ").replace(" oleh ", " ")
    return re.sub(r"\s+", " ", query).strip()
