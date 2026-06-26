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
    CaptionBox AV Stabilizer 2.1

    Cel:
    - operator widzi szybkie rozpoznanie robocze,
    - publiczność widzi stabilniejszy tekst,
    - końcówki zdań nie są zjadane,
    - stare fragmenty z bufora nie wracają jako duplikaty.

    Najważniejsza zmiana względem poprzedniej wersji:
    przy pauzie zatwierdzamy ostatnią roboczą hipotezę, zanim zamkniemy wypowiedź.
    Dzięki temu słowa, które były widoczne u operatora przez 1-2 sekundy, nie giną.
    """

    def __init__(
        self,
        audio_buffer,
        whisper_engine,
        sample_rate=44100,
        context_seconds=9.0,
        recent_rms_seconds=0.55,
        silence_threshold=0.0035,
        process_interval_seconds=0.65,
        pause_commit_seconds=0.95,
        max_history_blocks=14,
        max_current_words=46,
        max_current_chars=340,
        min_commit_words=2,
        stable_repetitions_required=2,
        unstable_tail_words=2,
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
        self.unstable_tail_words = max(0, int(unstable_tail_words))

        self.history: List[str] = []
        self.current = ""
        self.note = "gotowy"

        self.last_process_time = 0.0
        self.last_voice_time = time.time()
        self.last_state_signature = None

        # Each item: (original_words, normalized_words)
        self.hypotheses: List[Tuple[List[str], List[str]]] = []
        self.last_raw_words: List[str] = []
        self.last_raw_norm_words: List[str] = []
        self.last_raw_time = 0.0

        # Words already shown to the audience in the current session.
        self.committed_norm_words: List[str] = []
        self.recent_committed_blocks_norm: List[str] = []

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

        # Koniec wypowiedzi: zanim zamkniemy blok, dopisz ostatni roboczy tekst.
        # To naprawia zjadanie końcówek zdań widocznych u operatora.
        if recent_silent and self.current and pause_elapsed >= self.pause_commit_seconds:
            added = self._commit_tail_from_last_raw(force=True)
            self._finalize_current()
            self._clear_hypotheses()
            self.note = "pauza / zapisano wypowiedź" + (" + końcówka" if added else "")
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

        self.last_raw_words = raw_words
        self.last_raw_norm_words = raw_norm_words
        self.last_raw_time = now

        self.hypotheses.append((raw_words, raw_norm_words))
        self.hypotheses = self.hypotheses[-self.stable_repetitions_required:]

        stable_words, stable_norm_words = self._stable_prefix_from_hypotheses()
        draft = self._build_operator_draft(raw_words, raw_norm_words, stable_norm_words)

        if stable_words:
            new_words, new_norm_words = self._remove_already_committed(stable_words, stable_norm_words)
            new_text = self._sanitize_candidate(" ".join(new_words))
            if new_text and not self._looks_like_tail_noise(new_text):
                self._append_to_current(new_text)
                self.note = "zatwierdzono fragment"
            else:
                self.note = "robocze / echo"
        else:
            self.note = "robocze"

        # Jeśli blok robi się za długi, dopisz także aktualny ogon i zamknij blok.
        if self._current_should_finalize():
            self._commit_tail_from_last_raw(force=True)
            self._finalize_current()
            self._clear_hypotheses()
            self.note = "limit bloku / zapisano wypowiedź"

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

        # Nie publikuj od razu 1-2 ostatnich słów, bo Whisper często jeszcze je poprawia.
        # Ale nie trzymaj za dużo, bo wtedy zjadamy końcówki.
        if self.unstable_tail_words > 0 and prefix_len > self.unstable_tail_words:
            prefix_len -= self.unstable_tail_words
        elif prefix_len < len(latest_norm):
            prefix_len = 0

        return latest_words[:prefix_len], latest_norm[:prefix_len]

    def _commit_tail_from_last_raw(self, force=False):
        if not self.last_raw_words or not self.last_raw_norm_words:
            return False

        # Jeżeli ostatni wynik jest bardzo stary, nie używaj go jako końcówki.
        if not force and time.time() - self.last_raw_time > 2.5:
            return False

        words, norm_words = self._remove_already_committed(
            self.last_raw_words,
            self.last_raw_norm_words,
        )
        text = self._sanitize_candidate(" ".join(words))
        if not text:
            return False

        # Przy pauzie dopuszczamy krótsze końcówki, ale nadal blokujemy ewidentne echo.
        if self._looks_like_tail_noise(text) and len(text.split()) <= 2:
            return False

        before = self._norm(self.current)
        self._append_to_current(text)
        after = self._norm(self.current)
        return after != before

    def _build_operator_draft(self, raw_words, raw_norm_words, stable_norm_words):
        if not raw_words:
            return ""
        start = len(stable_norm_words)
        if start >= len(raw_words):
            draft_words = raw_words[-min(len(raw_words), 18):]
        else:
            draft_words = raw_words[start:]
        return self._clean(" ".join(draft_words[-30:]))

    def _remove_already_committed(self, words, norm_words):
        if not words or not norm_words:
            return [], []

        committed = self.committed_norm_words
        if not committed:
            return words, norm_words

        # Najpierw klasyczny overlap: koniec zatwierdzonego == początek nowego.
        best = 0
        max_overlap = min(len(committed), len(norm_words), 180)
        for overlap in range(1, max_overlap + 1):
            if committed[-overlap:] == norm_words[:overlap]:
                best = overlap
        if best > 0:
            return words[best:], norm_words[best:]

        # Jeżeli początek nowego tekstu jest już gdzieś w ogonie historii, odetnij go.
        tail = committed[-220:]
        max_probe = min(14, len(norm_words))
        for probe in range(max_probe, 2, -1):
            seq = norm_words[:probe]
            idx = self._find_sequence(tail, seq)
            if idx >= 0:
                return words[probe:], norm_words[probe:]

        candidate_norm = " ".join(norm_words)
        for old in self.recent_committed_blocks_norm[-10:]:
            if candidate_norm == old or self._ratio(candidate_norm, old) > 0.90:
                return [], []

        return words, norm_words

    def _append_to_current(self, text):
        text = self._clean(text)
        if not text:
            return

        text = self._remove_word_repeats(text)
        text = self._remove_phrase_repeats(text)

        if not self.current:
            self.current = text
            self._remember_committed_words(text)
            return

        current_norm_words = self._norm(self.current).split()
        text_words = text.split()
        text_norm_words = [self._norm_word(w) for w in text_words]
        text_words, text_norm_words = self._drop_empty_word_pairs(text_words, text_norm_words)

        # Jeżeli nowy fragment jest już w aktualnym bloku, nie dodawaj go drugi raz.
        text_norm = " ".join(text_norm_words)
        current_norm = " ".join(current_norm_words)
        if text_norm and (text_norm in current_norm or self._ratio(text_norm, current_norm) > 0.94):
            return

        # Usuń overlap między aktualnym blokiem i dopisywanym fragmentem.
        best = 0
        max_overlap = min(len(current_norm_words), len(text_norm_words), 80)
        for overlap in range(1, max_overlap + 1):
            if current_norm_words[-overlap:] == text_norm_words[:overlap]:
                best = overlap

        if best > 0:
            text_words = text_words[best:]
            text_norm_words = text_norm_words[best:]

        text = self._clean(" ".join(text_words))
        if not text:
            return

        combined = self._clean((self.current + " " + text).strip())
        combined = self._remove_word_repeats(combined)
        combined = self._remove_phrase_repeats(combined)
        self.current = combined
        self._remember_committed_words(text)

    def _remember_committed_words(self, text):
        norm_words = self._norm(text).split()
        if norm_words:
            self.committed_norm_words.extend(norm_words)
            self.committed_norm_words = self.committed_norm_words[-800:]

    def _finalize_current(self):
        # Na wszelki wypadek jeszcze raz dopisz aktualny roboczy ogon.
        self._commit_tail_from_last_raw(force=True)

        text = self._clean(self.current)
        if not text:
            self.current = ""
            return

        text = self._remove_word_repeats(text)
        text = self._remove_phrase_repeats(text)
        text = self._clean(text)

        if len(text.split()) < self.min_commit_words and self.history:
            self.current = ""
            return

        if not self._is_duplicate_history(text):
            self.history.append(text)
            self.history = self.history[-self.max_history_blocks:]
            self.recent_committed_blocks_norm.append(self._norm(text))
            self.recent_committed_blocks_norm = self.recent_committed_blocks_norm[-24:]

        self.current = ""

    def _current_should_finalize(self):
        if not self.current:
            return False
        words = self.current.split()
        if len(words) >= self.max_current_words:
            return True
        if len(self.current) >= self.max_current_chars:
            return True
        if re.search(r"[.!?…]$", self.current.strip()) and len(words) >= 10:
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
        for old in self.recent_committed_blocks_norm[-10:]:
            if norm == old or self._ratio(norm, old) > 0.92:
                return ""
        return text

    def _looks_like_tail_noise(self, text):
        words = text.split()
        if not words:
            return True

        norm = self._norm(text)
        if len(words) == 1 and len(norm) <= 3:
            return True

        # Krótkie echo z historii blokujemy, ale nie za agresywnie,
        # bo końcówki zdań często mają właśnie 2-4 słowa.
        if len(words) <= 2:
            committed_text = " ".join(self.committed_norm_words[-180:])
            if norm and norm in committed_text:
                return True

        return False

    def _is_duplicate_history(self, text):
        norm = self._norm(text)
        if not norm:
            return True
        for old in self.recent_committed_blocks_norm[-12:]:
            if norm == old or self._ratio(norm, old) > 0.92:
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
        self.last_raw_words = []
        self.last_raw_norm_words = []

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
            for n in range(10, 1, -1):
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
