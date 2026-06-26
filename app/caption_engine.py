import difflib
import re
import time
from dataclasses import dataclass
from typing import List, Tuple


@dataclass
class CaptionState:
    history: list
    current: str
    draft: str
    rms: float
    note: str


class CaptionEngine:
    """
    CaptionBox AV stabilizer.

    This version is deliberately conservative:
    - Whisper may rewrite the last words internally.
    - The operator sees the latest raw/draft hypothesis.
    - The audience only sees words that survived in consecutive hypotheses.

    The goal is not to show every possible partial word immediately. The goal is a
    stable conference caption that does not duplicate previous utterances and does
    not leave random tail words after speech stops.
    """

    def __init__(
        self,
        audio_buffer,
        whisper_engine,
        sample_rate=44100,
        context_seconds=10.0,
        recent_rms_seconds=0.65,
        silence_threshold=0.0035,
        process_interval_seconds=0.80,
        pause_commit_seconds=1.05,
        max_history_blocks=14,
        max_current_words=38,
        max_current_chars=260,
        min_commit_words=2,
        stable_repetitions_required=2,
        unstable_tail_words=4,
    ):
        self.audio_buffer = audio_buffer
        self.whisper_engine = whisper_engine
        self.sample_rate = int(sample_rate)
        self.context_seconds = float(context_seconds)
        self.recent_rms_seconds = float(recent_rms_seconds)
        self.silence_threshold = float(silence_threshold)
        self.process_interval_seconds = float(process_interval_seconds)
        self.pause_commit_seconds = float(pause_commit_seconds)
        self.max_history_blocks = int(max_history_blocks)
        self.max_current_words = int(max_current_words)
        self.max_current_chars = int(max_current_chars)
        self.min_commit_words = int(min_commit_words)
        self.stable_repetitions_required = max(2, int(stable_repetitions_required))
        self.unstable_tail_words = max(1, int(unstable_tail_words))

        self.history: List[str] = []
        self.current = ""
        self.last_process_time = 0.0
        self.last_voice_time = time.time()
        self.last_state_signature = None

        # Each item is: (original_words_from_raw, normalized_words_from_raw)
        self.hypotheses: List[Tuple[List[str], List[str]]] = []

        self.committed_norm_words: List[str] = []
        self.recent_committed_blocks_norm: List[str] = []
        self.last_published_norm_tail: List[str] = []
        self.note = "gotowy"

    def process_once(self):
        now = time.time()
        if now - self.last_process_time < self.process_interval_seconds:
            return None
        self.last_process_time = now

        recent, context = self.audio_buffer.get_recent_and_context(
            recent_seconds=self.recent_rms_seconds,
            context_seconds=self.context_seconds,
        )
        recent_rms = self.audio_buffer.rms(recent)
        context_rms = self.audio_buffer.rms(context)
        rms = max(recent_rms, context_rms)

        if len(context) < int(1.0 * self.sample_rate):
            self.note = "zbieram bufor"
            return self._state(rms, "")

        recent_silent = recent_rms < self.silence_threshold
        context_silent = context_rms < self.silence_threshold

        if not recent_silent:
            self.last_voice_time = now

        pause_elapsed = now - self.last_voice_time

        # Natural end of an utterance: freeze current and start a new block.
        if recent_silent and self.current and pause_elapsed >= self.pause_commit_seconds:
            self._finalize_current()
            self._clear_hypotheses()
            self.note = "pauza / zapisano wypowiedź"
            return self._state(rms, "")

        if recent_silent and context_silent:
            self.note = "cisza"
            return self._state(rms, "")

        raw = self.whisper_engine.transcribe_audio(context, self.sample_rate)
        raw = self._clean(raw)

        if not raw or self._is_bad_text(raw):
            self.note = "brak tekstu"
            return self._state(rms, "")

        raw_words = raw.split()
        raw_norm_words = [self._norm_word(w) for w in raw_words]
        raw_words, raw_norm_words = self._drop_empty_word_pairs(raw_words, raw_norm_words)

        if not raw_words:
            self.note = "brak tekstu"
            return self._state(rms, "")

        self.hypotheses.append((raw_words, raw_norm_words))
        self.hypotheses = self.hypotheses[-self.stable_repetitions_required:]

        stable_words, stable_norm_words = self._stable_prefix_from_hypotheses()
        draft = self._build_operator_draft(raw_words, raw_norm_words, stable_norm_words)

        if not stable_words:
            self.note = "robocze"
            return self._state(rms, draft)

        new_words, new_norm_words = self._remove_already_committed(stable_words, stable_norm_words)
        new_text = self._clean(" ".join(new_words))
        new_text = self._sanitize_candidate(new_text)

        if new_text and not self._looks_like_tail_noise(new_text):
            self._append_to_current(new_text)
            self.note = "zatwierdzono fragment"

            if self._current_should_finalize():
                self._finalize_current()
                self._clear_hypotheses()
                self.note = "limit bloku / zapisano wypowiedź"
        else:
            self.note = "pominięto echo/ogon"

        return self._state(rms, draft)

    def _state(self, rms, draft):
        state = CaptionState(
            history=list(self.history),
            current=self.current,
            draft=draft or "",
            rms=float(rms),
            note=self.note,
        )
        signature = (
            tuple(state.history),
            state.current,
            state.draft,
            round(state.rms, 4),
            state.note,
        )
        if signature == self.last_state_signature:
            return None
        self.last_state_signature = signature
        return state

    def _stable_prefix_from_hypotheses(self):
        if len(self.hypotheses) < self.stable_repetitions_required:
            return [], []

        latest_words, latest_norm = self.hypotheses[-1]
        prefix_len = len(latest_norm)

        for _, other_norm in self.hypotheses[:-1]:
            common = 0
            for a, b in zip(latest_norm, other_norm):
                if a == b:
                    common += 1
                else:
                    break
            prefix_len = min(prefix_len, common)

        # Keep a short unstable tail out of the audience view. This prevents
        # "Konstantynopolitańczy..." style endings from being published too soon.
        if prefix_len > self.unstable_tail_words:
            prefix_len -= self.unstable_tail_words
        elif prefix_len < len(latest_norm):
            prefix_len = 0

        return latest_words[:prefix_len], latest_norm[:prefix_len]

    def _build_operator_draft(self, raw_words, raw_norm_words, stable_norm_words):
        if not raw_words:
            return ""

        start = len(stable_norm_words)
        if start >= len(raw_words):
            draft_words = raw_words[-min(len(raw_words), 14):]
        else:
            draft_words = raw_words[start:]

        text = self._clean(" ".join(draft_words[-24:]))
        return text

    def _remove_already_committed(self, words, norm_words):
        if not words or not norm_words:
            return [], []

        committed = self.committed_norm_words
        if not committed:
            return words, norm_words

        best = 0
        max_overlap = min(len(committed), len(norm_words), 120)
        for overlap in range(1, max_overlap + 1):
            if committed[-overlap:] == norm_words[:overlap]:
                best = overlap

        if best > 0:
            return words[best:], norm_words[best:]

        candidate_norm = " ".join(norm_words)
        # Drop if this is just a previous block echoed by the rolling context.
        for old in self.recent_committed_blocks_norm[-8:]:
            if candidate_norm == old or self._ratio(candidate_norm, old) > 0.88:
                return [], []

        # Extra guard: if the first several words are already somewhere in the
        # committed tail, trim up to that local match.
        tail = committed[-160:]
        max_probe = min(10, len(norm_words))
        for probe in range(max_probe, 2, -1):
            seq = norm_words[:probe]
            idx = self._find_sequence(tail, seq)
            if idx >= 0:
                return words[probe:], norm_words[probe:]

        return words, norm_words

    def _append_to_current(self, text):
        text = self._clean(text)
        if not text:
            return

        existing_norm = self._norm(self.current)
        new_norm = self._norm(text)

        if existing_norm and (new_norm in existing_norm or self._ratio(new_norm, existing_norm) > 0.90):
            return

        combined = self._clean((self.current + " " + text).strip())
        combined = self._remove_word_repeats(combined)
        combined = self._remove_phrase_repeats(combined)

        old_norm_count = len(self._norm(self.current).split())
        new_norm_words = self._norm(combined).split()
        self.committed_norm_words.extend(new_norm_words[old_norm_count:])
        self.committed_norm_words = self.committed_norm_words[-500:]

        self.current = combined
        self.last_published_norm_tail = self._norm(self.current).split()[-40:]

    def _finalize_current(self):
        text = self._clean(self.current)
        if not text:
            self.current = ""
            return

        if len(text.split()) < self.min_commit_words and self.history:
            self.current = ""
            return

        if not self._is_duplicate_history(text):
            self.history.append(text)
            self.history = self.history[-self.max_history_blocks:]
            self.recent_committed_blocks_norm.append(self._norm(text))
            self.recent_committed_blocks_norm = self.recent_committed_blocks_norm[-20:]

        self.current = ""

    def _current_should_finalize(self):
        if not self.current:
            return False
        words = self.current.split()
        if len(words) >= self.max_current_words:
            return True
        if len(self.current) >= self.max_current_chars:
            return True
        if re.search(r"[.!?…]$", self.current.strip()) and len(words) >= 7:
            return True
        return False

    def _sanitize_candidate(self, text):
        text = self._clean(text)
        text = self._remove_word_repeats(text)
        text = self._remove_phrase_repeats(text)
        text = self._remove_history_echo(text)
        return self._clean(text)

    def _remove_history_echo(self, text):
        if not text:
            return ""
        norm = self._norm(text)
        if not norm:
            return ""
        for old in self.recent_committed_blocks_norm[-8:]:
            if norm == old or self._ratio(norm, old) > 0.88:
                return ""
        return text

    def _looks_like_tail_noise(self, text):
        words = text.split()
        if not words:
            return True

        norm = self._norm(text)
        if len(words) == 1 and len(norm) <= 3:
            return True

        # Short fragments that are contained in already displayed text are usually
        # the useless ASR tail after a longer phrase.
        if len(words) <= 3:
            committed_text = " ".join(self.committed_norm_words[-160:])
            if norm and (norm in committed_text):
                return True
            for old in self.recent_committed_blocks_norm[-8:]:
                if norm in old or self._ratio(norm, old) > 0.74:
                    return True

        return False

    def _is_duplicate_history(self, text):
        norm = self._norm(text)
        if not norm:
            return True
        for old in self.recent_committed_blocks_norm[-10:]:
            if norm == old or self._ratio(norm, old) > 0.88:
                return True
        return False

    def _is_bad_text(self, text):
        norm = self._norm(text)
        if len(norm) < 2:
            return True
        bad = {
            "napisy stworzone przez społeczność amara org",
            "napisy stworzone przez spolecznosc amara org",
            "dziękuję za uwagę",
            "dziekuje za uwage",
            "koniec",
        }
        if norm in bad:
            return True
        words = norm.split()
        if len(words) >= 3 and len(set(words)) == 1:
            return True
        return False

    def _clear_hypotheses(self):
        self.hypotheses = []

    def _drop_empty_word_pairs(self, words, norm_words):
        out_words = []
        out_norm = []
        for w, n in zip(words, norm_words):
            if n:
                out_words.append(w)
                out_norm.append(n)
        return out_words, out_norm

    def _find_sequence(self, haystack, needle):
        if not needle or len(needle) > len(haystack):
            return -1
        for i in range(0, len(haystack) - len(needle) + 1):
            if haystack[i:i + len(needle)] == needle:
                return i
        return -1

    def _remove_word_repeats(self, text):
        result = []
        for word in text.split():
            if result and self._norm_word(word) == self._norm_word(result[-1]):
                continue
            result.append(word)
        return " ".join(result)

    def _remove_phrase_repeats(self, text):
        words = text.split()
        if len(words) < 4:
            return text
        out = []
        i = 0
        while i < len(words):
            repeated = False
            for n in range(8, 1, -1):
                a = words[i:i+n]
                b = words[i+n:i+n*2]
                if len(a) == n and len(b) == n and self._norm(" ".join(a)) == self._norm(" ".join(b)):
                    out.extend(a)
                    i += n * 2
                    repeated = True
                    break
            if not repeated:
                out.append(words[i])
                i += 1
        return " ".join(out)

    def _clean(self, text):
        text = text or ""
        text = text.replace("♪", " ")
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def _norm_word(self, word):
        return re.sub(r"[^\wąćęłńóśźżĄĆĘŁŃÓŚŹŻ]", "", (word or "").lower()).strip()

    def _norm(self, text):
        text = (text or "").lower()
        text = re.sub(r"[^\wąćęłńóśźżĄĆĘŁŃÓŚŹŻ ]", "", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def _ratio(self, a, b):
        if not a or not b:
            return 0.0
        return difflib.SequenceMatcher(None, a, b).ratio()
