"""Turns streamed LLM text into speakable sentences as early as possible; extra detail goes to the screen."""

from __future__ import annotations

import re

DETAIL_RE = re.compile(r"\[\s*detail\s*\]", re.IGNORECASE)  # marker: everything after it is screen-only
_PUNCTUATION = re.compile(r"[.!?…]+[\"'”’)\]]*")
ABBREVIATIONS = {  # a period after these does not end a sentence
    "dr", "drs", "dra", "prof", "ir", "jl", "jln", "no", "tn", "ny", "sdr", "st", "rp", "pt", "cv",
    "tbk", "bpk", "hj", "kh", "mr", "mrs", "ms", "vs", "dkk", "yth", "a.n", "s.h", "s.e", "s.kom",
    "s.t", "m.m", "etc", "e.g", "i.e", "jan", "feb", "mar", "apr", "jun", "jul", "agu", "agt",
    "sep", "sept", "okt", "nov", "des",
}


class HiddenTagFilter:
    """Hides <think> reasoning and stray <tool_call> text from speech, even when a tag is split across chunks."""

    TAGS = ("think", "tool_call")

    def __init__(self) -> None:
        self._buffer = ""
        self._inside: str | None = None

    def feed(self, text: str) -> str:
        """Return the visible part of this chunk; hold back a tag that may still be arriving."""
        self._buffer += text
        visible: list[str] = []
        while self._buffer:
            if self._inside:
                closing = f"</{self._inside}>"
                index = self._buffer.find(closing)
                if index < 0:
                    keep = _partial_suffix(self._buffer, closing)
                    self._buffer = self._buffer[len(self._buffer) - keep :] if keep else ""
                    break
                self._buffer = self._buffer[index + len(closing) :]
                self._inside = None
                continue

            earliest: tuple[int, str] | None = None
            for tag in self.TAGS:
                index = self._buffer.find(f"<{tag}>")
                if index >= 0 and (earliest is None or index < earliest[0]):
                    earliest = (index, tag)
            if earliest is not None:
                index, tag = earliest
                visible.append(self._buffer[:index])
                self._buffer = self._buffer[index + len(tag) + 2 :]
                self._inside = tag
                continue

            keep = max(_partial_suffix(self._buffer, f"<{tag}>") for tag in self.TAGS)
            if keep:
                visible.append(self._buffer[:-keep])
                self._buffer = self._buffer[-keep:]
            else:
                visible.append(self._buffer)
                self._buffer = ""
            break
        return "".join(visible)

    def flush(self) -> str:
        """End of response: release held text, but drop an unclosed hidden block."""
        rest, self._buffer = self._buffer, ""
        inside, self._inside = self._inside, None
        return "" if inside else rest


def _partial_suffix(text: str, token: str) -> int:
    """Length of the longest suffix of `text` that is a proper prefix of `token`."""
    for size in range(min(len(token) - 1, len(text)), 0, -1):
        if text.endswith(token[:size]):
            return size
    return 0


class SpeechSegmenter:
    """Splits streamed text into sentences with a spoken-sentence budget; overflow and [DETAIL] go to the screen."""

    def __init__(self, max_sentences: int = 3, soft_limit: int = 160):
        self.max_sentences = max(1, max_sentences)
        self.soft_limit = soft_limit  # split a very long first sentence at a comma so audio starts sooner
        self.overflowed = False
        self._buffer = ""
        self._count = 0
        self._detail_mode = False
        self._detail: list[str] = []

    @property
    def detail(self) -> str:
        """Text meant for the screen, not for speech."""
        return "".join(self._detail).strip()

    def new_step(self) -> None:
        """A new LLM response in the same turn (after a tool call) gets its own sentence budget."""
        self._count = 0
        self._detail_mode = False
        self._buffer = ""

    def feed(self, text: str) -> list[str]:
        """Add streamed text; return the sentences that are complete and should be spoken now."""
        if not text:
            return []
        if self._detail_mode:
            self._detail.append(text)
            return []

        self._buffer += text
        marker = DETAIL_RE.search(self._buffer)
        if marker:
            head, tail = self._buffer[: marker.start()], self._buffer[marker.end() :]
            self._buffer = head
            sentences = self._drain(final=True)
            self._enter_detail(tail)
            return sentences

        held = ""  # hold back a marker that is still streaming in, e.g. "...selesai. [DET"
        bracket = self._buffer.rfind("[")
        if bracket >= 0 and "]" not in self._buffer[bracket:] and len(self._buffer) - bracket <= 10:
            held = self._buffer[bracket:]
            self._buffer = self._buffer[:bracket]
        sentences = self._drain(final=False)
        if held:
            if self._detail_mode:
                self._detail.append(held)
            else:
                self._buffer += held
        return sentences

    def flush(self) -> list[str]:
        """End of a response: speak whatever is left, unless the rest belongs to the screen."""
        if self._detail_mode:
            return []
        return self._drain(final=True)

    def _enter_detail(self, text: str = "") -> None:
        """Switch to screen-only mode for the rest of this response."""
        self._detail_mode = True
        if self._buffer.strip():
            self._detail.append(self._buffer)
        self._buffer = ""
        if text:
            self._detail.append(text)

    def _drain(self, final: bool) -> list[str]:
        """Pop complete sentences until none is left or the budget is used up."""
        sentences: list[str] = []
        while True:
            self._buffer = self._buffer.lstrip()
            if self._count >= self.max_sentences:
                if self._buffer:
                    self.overflowed = True
                    self._enter_detail()
                break
            cut = self._find_cut(final)
            if cut is None:
                if final and self._buffer:
                    sentences.append(self._buffer.strip())
                    self._count += 1
                    self._buffer = ""
                break
            sentence = self._buffer[:cut].strip()
            self._buffer = self._buffer[cut:]
            if sentence:
                sentences.append(sentence)
                self._count += 1
        return sentences

    def _find_cut(self, final: bool) -> int | None:
        """Index where the next sentence ends, or None if more text is needed to be sure."""
        text = self._buffer
        best: int | None = None
        newline = text.find("\n")
        if newline > 0:
            best = newline + 1

        for match in _PUNCTUATION.finditer(text):
            end = match.end()
            if best is not None and end >= best:
                break
            rest = text[end:]
            if not rest:
                break  # need the next character to know whether the sentence really ended
            if not rest[0].isspace():
                continue  # "3.5", "kompas.com"
            after = rest.lstrip()
            if not after:
                if final:
                    return end
                break
            if set(match.group()) & set(".") and not set(match.group()) & set("!?…"):
                word = _last_word(text[: match.start()])
                if word in ABBREVIATIONS or (len(word) == 1 and word.isalpha()):
                    continue  # "Dr. Budi", "B. J. Habibie"
                if after[0].islower():
                    continue  # "dll. juga" continues the sentence
            return end

        if best is not None:
            return best
        if not final and len(text) > self.soft_limit:
            cut = max(text.rfind(", ", 40, self.soft_limit), text.rfind("; ", 40, self.soft_limit))
            if cut > 0:
                return cut + 1
        return None


def _last_word(text: str) -> str:
    """The word before a period, to recognise abbreviations like "Dr." or "Rp."."""
    match = re.search(r"(\S+)$", text)
    return match.group(1).strip("([\"'").lower() if match else ""


_URL = re.compile(r"https?://\S+|www\.\S+")
_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿️‍]")
_BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")


def clean_for_speech(text: str) -> str:
    """Strip what TTS would read literally: markdown, URLs, emoji, list bullets."""
    text = _MD_LINK.sub(r"\1", text)
    text = _URL.sub("", text)
    text = _BULLET.sub("", text)
    text = re.sub(r"[*_`#>|~]+", " ", text)
    text = _EMOJI.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+([.,!?])", r"\1", text)
    return text if re.search(r"\w", text) else ""
