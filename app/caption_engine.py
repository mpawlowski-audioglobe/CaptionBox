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
    CaptionBox AV Stabilizer 3.0

    Założenia:
    - okno operatora widzi najnowszą hipotezę roboczą,
    - okno publiczności widzi tekst stabilizowany,
    - historia jest niezmienna: raz zapisany blok nie jest później poprawiany,
    - aktualna wypowiedź może być poprawiana, ale nie powinna powielać historii,
    - po pauzie zatwierdzamy ostatnią pełną hipotezę, żeby nie zjadać końcówek zdań.

    Największa różnica względem poprzedniej wersji:
    nie dopisujemy kolejnych fragmentów Whispera do publicznego tekstu metodą append.
    Zamiast tego wyciągamy z rolling-context tylko bieżącą wypowiedź i publikujemy jej
    stabilny prefiks. To mocno ogranicza powtórzenia typu „Naszym celem... Naszym celem...”.
    """

    def __init__(
        self,
        audio_buffer,
        whisper_engine,
        sample_rate=44100,
        context_seconds=9.0,
        recent_rms_seconds=0.55,
        silence_threshold=0.0035,
        process_interval_seconds=0.60,
        pause_commit_seconds=0.90,
        max_history_blocks=18,
        max_current_words=56,
        max_current_chars=430,
        min_commit_words=2,
        stable_repetitions_required=2,
        unstable_tail_words=1,
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

        # Candidate == aktualna wypowiedź wycięta z pełnego rolling-contextu.
        # Each item: (original_words, normalized_words)
        self.candidates: List[Tuple[List[str], List[str]]] = []
        self.last_candidate_words: List[str] = []
        self.last_candidate_norm_words: List[str] = []
        self.last_candidate_time = 0.0
        self.last_raw_text = ""

        # Finalized words from history only. Current public block is intentionally not here,
        # because it may still be updated before finalization.
        self.history_norm_words: List[str] = []
        self.recent_history_norm_blocks: List[str] = []

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

        # Koniec wypowiedzi. To jest najważniejszy moment:
        # zatwierdzamy ostatnią kompletną hipotezę, nawet jeśli stabilny prefiks był krótszy.
        if recent_silent and pause_elapsed >= self.pause_commit_seconds:
            finalized = self._finalize_from_last_candidate()
            self._clear_candidates()
            self.note = "pauza / zapisano wypowiedź" if finalized else "pauza"
            return self._state(rms, "")

        if recent_silent and context_silent:
            self.note = "cisza"
            return self._state(rms, "")

        raw = self.whisper_engine.transcribe_audio(context, self.sample_rate)
        raw = self._clean(raw)
        self.last_raw_text = raw

        if not raw or self._is_bad_text(raw):
            self.note = "brak tekstu"
            return self._state(rms, "")

        raw_words, raw_norm_words = self._words_and_norm(raw)
        if not raw_words:
            self.note = "brak tekstu"
            return self._state(rms, "")

        candidate_words, candidate_norm_words = self._extract_current_candidate(raw_words, raw_norm_words)
        candidate_text = self._sanitize_candidate(" ".join(candidate_words))
        candidate_words, candidate_norm_words = self._words_and_norm(candidate_text)

        if not candidate_words:
            self.note = "echo historii"
            return self._state(rms, "")

        self.last_candidate_words = candidate_words
        self.last_candidate_norm_words = candidate_norm_words
        self.last_candidate_time = now

        self.candidates.append((candidate_words, candidate_norm_words))
        self.candidates = self.candidates[-self.stable_repetitions_required:]

        stable_words, stable_norm_words = self._stable_prefix_from_candidates()
        draft = self._build_operator_draft(candidate_words, stable_norm_words)

        if stable_words:
            stable_text = self._sanitize_candidate(" ".join(stable_words))
            if stable_text and not self._looks_like_noise(stable_text):
                self._set_current_public_text(stable_text)
                self.note = "zatwierdzono stabilny fragment"
            else:
                self.note = "robocze / filtr"
        else:
            self.note = "robocze"

        if self._current_should_finalize():
            self._finalize_from_last_candidate(prefer_current=True)
            self._clear_candidates()
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

    def _extract_current_candidate(self, raw_words, raw_norm_words):
        if not self.history_norm_words:
            return raw_words, raw_norm_words

        history_tail = self.history_norm_words[-260:]

        # 1. Najczęstszy przypadek: koniec historii == początek rolling-contextu.
        best_prefix_overlap = 0
        max_overlap = min(len(history_tail), len(raw_norm_words), 220)
        for overlap in range(2, max_overlap + 1):
            if history_tail[-overlap:] == raw_norm_words[:overlap]:
                best_prefix_overlap = overlap
        if best_prefix_overlap > 0:
            return raw_words[best_prefix_overlap:], raw_norm_words[best_prefix_overlap:]

        # 2. Rolling-context czasem zaczyna się w środku historii. Szukamy mocnej kotwicy
        # z końca historii w dowolnym miejscu raw i bierzemy tekst po niej.
        best_end = -1
        best_len = 0
        max_anchor = min(28, len(history_tail), len(raw_norm_words))
        for anchor_len in range(max_anchor, 3, -1):
            anchor = history_tail[-anchor_len:]
            idx = self._find_sequence(raw_norm_words, anchor)
            if idx >= 0:
                best_end = idx + anchor_len
                best_len = anchor_len
                break
        if best_end >= 0 and best_len >= 4:
            return raw_words[best_end:], raw_norm_words[best_end:]

        # 3. Jeżeli pierwsze kilka słów raw jest bardzo podobne do ostatniego bloku historii,
        # odcinamy powtórzony początek ostrożnie.
        for probe in range(min(12, len(raw_norm_words)), 3, -1):
            raw_prefix = " ".join(raw_norm_words[:probe])
            for old in self.recent_history_norm_blocks[-6:]:
                if raw_prefix and raw_prefix in old:
                    return raw_words[probe:], raw_norm_words[probe:]

        return raw_words, raw_norm_words

    def _stable_prefix_from_candidates(self):
        if len(self.candidates) < self.stable_repetitions_required:
            return [], []

        latest_words, latest_norm = self.candidates[-1]
        prefix_len = len(latest_norm)

        for _, other_norm in self.candidates[:-1]:
            common = 0
            for a, b in zip(latest_norm, other_norm):
                if a == b:
                    common += 1
                else:
                    break
            prefix_len = min(prefix_len, common)

        # Trzymamy tylko ostatnie słowo jako robocze. Poprzednie wersje trzymały 2 słowa,
        # co powodowało zjadanie końcówek zdań.
        if self.unstable_tail_words > 0 and prefix_len > self.unstable_tail_words:
            prefix_len -= self.unstable_tail_words
        elif prefix_len < len(latest_norm):
            prefix_len = 0

        return latest_words[:prefix_len], latest_norm[:prefix_len]

    def _set_current_public_text(self, text):
        text = self._sanitize_candidate(text)
        if not text:
            return

        if not self.current:
            self.current = text
            return

        current_norm = self._norm(self.current)
        text_norm = self._norm(text)
        if not text_norm:
            return

        # Jeżeli nowa stabilna hipoteza rozszerza aktualny tekst, podmieniamy na dłuższą.
        if text_norm.startswith(current_norm):
            self.current = text
            return

        # Jeżeli aktualny tekst jest zawarty w nowym, też podmieniamy.
        if current_norm in text_norm:
            self.current = text
            return

        # Jeśli nowy tekst jest krótszy, ale bardzo podobny, nie cofaj publiczności.
        if self._ratio(current_norm, text_norm) > 0.86 and len(text_norm) <= len(current_norm):
            return

        # Jeżeli Whisper realnie zmienił hipotezę, ale ona jest dłuższa i podobna,
        # pozwalamy ją podmienić w aktualnym bloku. Historia nie jest ruszana.
        if self._ratio(current_norm, text_norm) > 0.62 and len(text_norm) > len(current_norm):
            self.current = text
            return

        # W innym wypadku traktujemy to jako nową myśl. Zamykamy bieżący blok,
        # ale nie pozwalamy na powielanie historii.
        if len(self.current.split()) >= self.min_commit_words:
            self._finalize_text(self.current)
        self.current = text

    def _finalize_from_last_candidate(self, prefer_current=False):
        if not self.last_candidate_words:
            if self.current:
                return self._finalize_text(self.current)
            return False

        candidate_text = self._sanitize_candidate(" ".join(self.last_candidate_words))
        current_text = self._sanitize_candidate(self.current)

        if prefer_current and current_text:
            text = self._choose_better_final(current_text, candidate_text)
        else:
            text = self._choose_better_final(current_text, candidate_text)

        return self._finalize_text(text)

    def _choose_better_final(self, current_text, candidate_text):
        current_text = self._clean(current_text)
        candidate_text = self._clean(candidate_text)

        if not candidate_text:
            return current_text
        if not current_text:
            return candidate_text

        c_norm = self._norm(current_text)
        cand_norm = self._norm(candidate_text)

        # Jeżeli kandydat zawiera aktualny tekst i dopowiada końcówkę, bierzemy kandydata.
        if c_norm and c_norm in cand_norm:
            return candidate_text

        # Jeżeli kandydat jest mocno podobny i dłuższy, zwykle zawiera końcówkę.
        if self._ratio(c_norm, cand_norm) > 0.70 and len(candidate_text) >= len(current_text):
            return candidate_text

        # Jeżeli kandydat jest ewidentnie echem historii albo bardzo krótki, zostaw current.
        if self._looks_like_noise(candidate_text) and len(candidate_text.split()) <= 3:
            return current_text

        # W pozostałych przypadkach preferujemy dłuższy tekst, ale bez przesady.
        if len(candidate_text.split()) >= len(current_text.split()):
            return candidate_text
        return current_text

    def _finalize_text(self, text):
        text = self._sanitize_candidate(text)
        if not text:
            self.current = ""
            return False

        words = text.split()
        if len(words) < self.min_commit_words and self.history:
            self.current = ""
            return False

        if self._is_duplicate_history(text):
            self.current = ""
            return False

        self.history.append(text)
        self.history = self.history[-self.max_history_blocks:]
        self._rebuild_history_memory()
        self.current = ""
        return True

    def _current_should_finalize(self):
        if not self.current:
            return False
        words = self.current.split()
        if len(words) >= self.max_current_words:
            return True
        if len(self.current) >= self.max_current_chars:
            return True
        # Kropka nie kończy od razu wypowiedzi, bo Whisper potrafi ją wstawić za wcześnie.
        # Finalizujemy po interpunkcji dopiero przy sensownej długości.
        if re.search(r"[.!?…]$", self.current.strip()) and len(words) >= 18:
            return True
        return False

    def _build_operator_draft(self, candidate_words, stable_norm_words):
        if not candidate_words:
            return ""
        stable_len = len(stable_norm_words)
        draft_words = candidate_words[stable_len:] if stable_len < len(candidate_words) else candidate_words[-12:]
        return self._clean(" ".join(draft_words[-34:]))

    def _sanitize_candidate(self, text):
        text = self._clean(text)
        text = self._remove_word_repeats(text)
        text = self._remove_phrase_repeats(text)
        text = self._strip_history_duplicate_prefix(text)
        return self._clean(text)

    def _strip_history_duplicate_prefix(self, text):
        words, norm_words = self._words_and_norm(text)
        if not words or not self.history_norm_words:
            return text

        history_tail = self.history_norm_words[-180:]
        best = 0
        max_overlap = min(len(history_tail), len(norm_words), 80)
        for overlap in range(2, max_overlap + 1):
            if history_tail[-overlap:] == norm_words[:overlap]:
                best = overlap
        if best > 0:
            return " ".join(words[best:])
        return text

    def _looks_like_noise(self, text):
        words = text.split()
        norm = self._norm(text)
        if not words or not norm:
            return True
        if len(words) == 1 and len(norm) <= 3:
            return True
        if len(words) <= 2 and self.history_norm_words:
            history_text = " ".join(self.history_norm_words[-160:])
            if norm in history_text:
                return True
        return False

    def _is_duplicate_history(self, text):
        norm = self._norm(text)
        if not norm:
            return True
        for old in self.recent_history_norm_blocks[-12:]:
            if norm == old or self._ratio(norm, old) > 0.90:
                return True
        return False

    def _is_bad_text(self, text):
        norm = self._norm(text)
        if len(norm) < 2:
            return True
        bad = {
            "napisy stworzone przez społeczność amara org",
            "napisy stworzone przez spolecznosc amara org",
            "muzyka",
        }
        if norm in bad:
            return True
        words = norm.split()
        if len(words) >= 3 and len(set(words)) == 1:
            return True
        return False

    def _rebuild_history_memory(self):
        self.history_norm_words = []
        self.recent_history_norm_blocks = []
        for block in self.history:
            norm = self._norm(block)
            if norm:
                self.recent_history_norm_blocks.append(norm)
                self.history_norm_words.extend(norm.split())
        self.history_norm_words = self.history_norm_words[-1200:]
        self.recent_history_norm_blocks = self.recent_history_norm_blocks[-32:]

    def _clear_candidates(self):
        self.candidates = []
        self.last_candidate_words = []
        self.last_candidate_norm_words = []
        self.last_candidate_time = 0.0

    def _words_and_norm(self, text):
        words = self._clean(text).split()
        out_words = []
        out_norm = []
        for word in words:
            norm = self._norm_word(word)
            if norm:
                out_words.append(word)
                out_norm.append(norm)
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
            for n in range(12, 1, -1):
                a = words[i:i + n]
                b = words[i + n:i + n * 2]
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
