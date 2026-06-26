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
    CaptionBox AV - Word Stabilizer v2.0

    Najważniejsze założenia:
    - Whisper może zwracać pełny rolling-context, więc nie wolno go bezpośrednio doklejać.
    - Historia jest niezmienna. Raz zatwierdzony blok nie jest później edytowany.
    - Aktualna wypowiedź może być korygowana przez model, ale publiczność widzi tylko wersję stabilną.
    - Po pauzie publikujemy pełną ostatnią hipotezę, żeby nie gubić końcówek zdań.
    - Stabilizacja działa na słowach, nie na znakach ani całych stringach.
    """

    def __init__(
        self,
        audio_buffer,
        whisper_engine,
        sample_rate=44100,
        context_seconds=9.0,
        recent_rms_seconds=0.55,
        silence_threshold=0.0035,
        process_interval_seconds=0.58,
        pause_commit_seconds=0.95,
        max_history_blocks=20,
        max_current_words=72,
        max_current_chars=560,
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

        # Hipotezy aktualnej wypowiedzi po odcięciu historii.
        self.candidates: List[Tuple[List[str], List[str]]] = []
        self.last_candidate_words: List[str] = []
        self.last_candidate_norm_words: List[str] = []
        self.last_candidate_time = 0.0
        self.last_raw_text = ""

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

        # Jeżeli zapadła pauza, zatwierdzamy pełną ostatnią hipotezę.
        # To jest celowe: stabilny prefiks może być krótszy, ale po pauzie nie wolno zgubić końcówki.
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

        # Jeżeli nowa hipoteza wygląda jak poprawiona wersja aktualnego bloku,
        # pozwalamy jej zastąpić current zamiast tworzyć nową wypowiedź.
        candidate_words, candidate_norm_words = self._repair_candidate_against_current(
            candidate_words,
            candidate_norm_words,
        )
        if not candidate_words:
            self.note = "robocze / filtr"
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
                self._update_current_public_text(stable_text)
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

    # ------------------------------------------------------------------
    # Extract current utterance from rolling context
    # ------------------------------------------------------------------
    def _extract_current_candidate(self, raw_words, raw_norm_words):
        if not self.history_norm_words:
            return raw_words, raw_norm_words

        history_tail = self.history_norm_words[-320:]

        # 1. Najsilniejszy przypadek: końcówka historii jest w środku rolling-contextu.
        # Bierzemy tekst po najdłuższej kotwicy. To dużo stabilniejsze niż samo sprawdzanie prefiksu.
        best_end = -1
        best_len = 0
        max_anchor = min(60, len(history_tail), len(raw_norm_words))
        for anchor_len in range(max_anchor, 3, -1):
            anchor = history_tail[-anchor_len:]
            idx = self._find_sequence(raw_norm_words, anchor)
            if idx >= 0:
                best_end = idx + anchor_len
                best_len = anchor_len
                break
        if best_end >= 0 and best_len >= 4:
            return raw_words[best_end:], raw_norm_words[best_end:]

        # 2. Gdy rolling-context zaczyna się dokładnie od końcówki historii.
        best_prefix_overlap = 0
        max_overlap = min(len(history_tail), len(raw_norm_words), 240)
        for overlap in range(2, max_overlap + 1):
            if history_tail[-overlap:] == raw_norm_words[:overlap]:
                best_prefix_overlap = overlap
        if best_prefix_overlap > 0:
            return raw_words[best_prefix_overlap:], raw_norm_words[best_prefix_overlap:]

        # 3. Odcinanie powtórzonego początku na podstawie ostatnich bloków historii.
        # Jeżeli pierwsze słowa raw są już końcówką historii, nie publikujemy ich ponownie.
        best_strip = 0
        max_probe = min(28, len(raw_norm_words))
        for probe in range(max_probe, 3, -1):
            raw_prefix = " ".join(raw_norm_words[:probe])
            if not raw_prefix:
                continue
            for old in self.recent_history_norm_blocks[-10:]:
                if raw_prefix in old:
                    best_strip = probe
                    break
            if best_strip:
                break
        if best_strip > 0:
            return raw_words[best_strip:], raw_norm_words[best_strip:]

        return raw_words, raw_norm_words

    def _repair_candidate_against_current(self, words, norm_words):
        if not self.current:
            return words, norm_words

        current_words, current_norm = self._words_and_norm(self.current)
        if not current_norm or not norm_words:
            return words, norm_words

        # Jeżeli kandydat jest tylko końcówką aktualnego tekstu, nie publikujemy go jako nowego bloku.
        cand_text_norm = " ".join(norm_words)
        current_text_norm = " ".join(current_norm)
        if cand_text_norm and cand_text_norm in current_text_norm and len(norm_words) <= len(current_norm):
            return [], []

        # Jeżeli kandydat zawiera aktualny tekst, to jest naturalne rozszerzenie.
        idx = self._find_sequence(norm_words, current_norm[-min(len(current_norm), 24):])
        if idx >= 0:
            # Zwracamy pełny kandydat. _update_current_public_text zajmie się podmianą/rozszerzeniem.
            return words, norm_words

        # Pozwól na korektę ostatniego słowa, np. „Po pauzie tak” -> „Po pauzie tekst powinien...”
        # Wspólne pierwsze słowa są ważniejsze niż dosłowna zgodność całego prefixu.
        common = self._common_prefix_len(current_norm, norm_words)
        if common >= max(2, min(len(current_norm), 6) - 1):
            return words, norm_words

        # Jeżeli oba teksty są podobne i kandydat jest dłuższy, traktujemy go jako poprawkę bieżącego bloku.
        ratio = self._ratio(current_text_norm, cand_text_norm)
        if ratio >= 0.58 and len(norm_words) >= len(current_norm):
            return words, norm_words

        return words, norm_words

    # ------------------------------------------------------------------
    # Stabilization and current block updates
    # ------------------------------------------------------------------
    def _stable_prefix_from_candidates(self):
        if len(self.candidates) < self.stable_repetitions_required:
            return [], []

        latest_words, latest_norm = self.candidates[-1]
        prefix_len = len(latest_norm)

        for _, other_norm in self.candidates[:-1]:
            prefix_len = min(prefix_len, self._common_prefix_len(latest_norm, other_norm))

        # Zostawiamy tylko ostatnie słowo jako robocze, żeby publiczność nie widziała niestabilnej końcówki.
        # Po pauzie pełna hipoteza i tak zostanie dopisana, więc końcówka nie zginie.
        if self.unstable_tail_words > 0 and prefix_len > self.unstable_tail_words:
            prefix_len -= self.unstable_tail_words
        elif prefix_len < len(latest_norm):
            prefix_len = 0

        return latest_words[:prefix_len], latest_norm[:prefix_len]

    def _update_current_public_text(self, text):
        text = self._sanitize_candidate(text)
        if not text:
            return

        if not self.current:
            self.current = text
            return

        current_words, current_norm_words = self._words_and_norm(self.current)
        text_words, text_norm_words = self._words_and_norm(text)
        if not text_norm_words:
            return

        current_norm = " ".join(current_norm_words)
        text_norm = " ".join(text_norm_words)

        # Nie cofamy publiczności do krótszej wersji tego samego tekstu.
        if current_norm.startswith(text_norm) and len(text_norm_words) <= len(current_norm_words):
            return

        # Naturalne rozszerzenie.
        if text_norm.startswith(current_norm):
            self.current = text
            return

        # Aktualny tekst jest w środku nowej hipotezy.
        if current_norm in text_norm:
            self.current = text
            return

        # Korekta ostatniego słowa lub dwóch końcowych słów.
        common = self._common_prefix_len(current_norm_words, text_norm_words)
        if common >= max(2, len(current_norm_words) - 2) and len(text_norm_words) >= common:
            self.current = text
            return

        # Silna korekta tej samej wypowiedzi: podobny początek i kandydat dłuższy.
        if common >= 2 and self._ratio(current_norm, text_norm) >= 0.56 and len(text_norm_words) >= len(current_norm_words):
            self.current = text
            return

        # Jeżeli nowy tekst jest bardzo podobny, ale krótszy, ignorujemy.
        if self._ratio(current_norm, text_norm) > 0.86 and len(text_norm_words) <= len(current_norm_words):
            return

        # Nowa myśl. Zapisz bieżący blok, potem rozpocznij kolejny.
        if len(current_words) >= self.min_commit_words:
            self._finalize_text(self.current)
        self.current = text

    # ------------------------------------------------------------------
    # Finalization
    # ------------------------------------------------------------------
    def _finalize_from_last_candidate(self, prefer_current=False):
        candidate_text = ""
        if self.last_candidate_words:
            candidate_text = self._sanitize_candidate(" ".join(self.last_candidate_words))
        current_text = self._sanitize_candidate(self.current)

        if prefer_current:
            final_text = self._choose_better_final(current_text, candidate_text)
        else:
            final_text = self._choose_better_final(current_text, candidate_text)

        return self._finalize_text(final_text)

    def _choose_better_final(self, current_text, candidate_text):
        current_text = self._clean(current_text)
        candidate_text = self._clean(candidate_text)

        if not candidate_text:
            return current_text
        if not current_text:
            return candidate_text

        current_words, current_norm_words = self._words_and_norm(current_text)
        cand_words, cand_norm_words = self._words_and_norm(candidate_text)
        current_norm = " ".join(current_norm_words)
        cand_norm = " ".join(cand_norm_words)

        if not cand_norm:
            return current_text
        if not current_norm:
            return candidate_text

        # Kandydat jest pełniejszą wersją aktualnego bloku.
        if current_norm in cand_norm:
            return candidate_text
        if cand_norm.startswith(current_norm):
            return candidate_text

        # Kandydat poprawia ostatnie słowo i dopowiada końcówkę.
        common = self._common_prefix_len(current_norm_words, cand_norm_words)
        if common >= max(2, len(current_norm_words) - 2) and len(cand_norm_words) >= len(current_norm_words):
            return candidate_text

        # Bardzo podobny i dłuższy kandydat zwykle zawiera końcówkę zdania.
        if self._ratio(current_norm, cand_norm) > 0.68 and len(cand_words) >= len(current_words):
            return candidate_text

        # Jeżeli kandydat wygląda jak szum, zostawiamy aktualny blok.
        if self._looks_like_noise(candidate_text) and len(cand_words) <= 3:
            return current_text

        # Domyślnie preferujemy dłuższą, ale sensowną wersję.
        if len(cand_words) >= len(current_words):
            return candidate_text
        return current_text

    def _finalize_text(self, text):
        text = self._sanitize_candidate(text)
        if not text:
            self.current = ""
            return False

        text = self._strip_history_duplicate_prefix(text)
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

        # Jeżeli nowy blok zaczyna się tak samo jak ostatni i jest jego rozszerzeniem,
        # aktualizujemy ostatni blok zamiast dodawać duplikat.
        if self.history:
            merged = self._merge_with_last_history_if_needed(text)
            if merged is not None:
                self.history[-1] = merged
                self.history = self.history[-self.max_history_blocks:]
                self._rebuild_history_memory()
                self.current = ""
                return True

        self.history.append(text)
        self.history = self.history[-self.max_history_blocks:]
        self._rebuild_history_memory()
        self.current = ""
        return True

    def _merge_with_last_history_if_needed(self, text):
        if not self.history:
            return None
        last = self.history[-1]
        last_words, last_norm = self._words_and_norm(last)
        words, norm = self._words_and_norm(text)
        if not last_norm or not norm:
            return None

        last_norm_text = " ".join(last_norm)
        norm_text = " ".join(norm)

        if norm_text == last_norm_text:
            return last

        if norm_text.startswith(last_norm_text):
            return text

        if last_norm_text.startswith(norm_text):
            return last

        common = self._common_prefix_len(last_norm, norm)
        if common >= max(4, min(len(last_norm), len(norm)) - 2):
            # Wybierz pełniejszy tekst.
            return text if len(words) >= len(last_words) else last

        # Zszywanie częściowo zachodzących bloków: koniec last == początek text.
        overlap = self._suffix_prefix_overlap(last_norm, norm, max_len=30)
        if overlap >= 3:
            return " ".join(last_words + words[overlap:])

        return None

    def _current_should_finalize(self):
        if not self.current:
            return False
        words = self.current.split()
        if len(words) >= self.max_current_words:
            return True
        if len(self.current) >= self.max_current_chars:
            return True
        # Interpunkcja finalizuje tylko dłuższe wypowiedzi; Whisper potrafi wstawiać kropki za wcześnie.
        if re.search(r"[.!?…]$", self.current.strip()) and len(words) >= 20:
            return True
        return False

    # ------------------------------------------------------------------
    # Cleanup and duplicate filters
    # ------------------------------------------------------------------
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

        history_tail = self.history_norm_words[-240:]
        best = 0
        max_overlap = min(len(history_tail), len(norm_words), 120)
        for overlap in range(2, max_overlap + 1):
            if history_tail[-overlap:] == norm_words[:overlap]:
                best = overlap
        if best > 0:
            return " ".join(words[best:])

        # Jeżeli cały początek jest fragmentem ostatniego bloku historii, odetnij go.
        for probe in range(min(24, len(norm_words)), 3, -1):
            prefix = " ".join(norm_words[:probe])
            for old in self.recent_history_norm_blocks[-8:]:
                if prefix in old:
                    return " ".join(words[probe:])
        return text

    def _looks_like_noise(self, text):
        words = text.split()
        norm = self._norm(text)
        if not words or not norm:
            return True
        if len(words) == 1 and len(norm) <= 3:
            return True
        if len(words) <= 2 and self.history_norm_words:
            history_text = " ".join(self.history_norm_words[-200:])
            if norm in history_text:
                return True
        return False

    def _is_duplicate_history(self, text):
        norm = self._norm(text)
        if not norm:
            return True
        words = norm.split()
        for old in self.recent_history_norm_blocks[-14:]:
            if norm == old:
                return True
            if len(words) >= 5 and self._ratio(norm, old) > 0.92:
                return True
            # Krótkie powtórki końcówek historii blokujemy ostrzej.
            if len(words) <= 6 and norm in old:
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

    def _build_operator_draft(self, candidate_words, stable_norm_words):
        if not candidate_words:
            return ""
        stable_len = len(stable_norm_words)
        if stable_len < len(candidate_words):
            draft_words = candidate_words[stable_len:]
        else:
            draft_words = candidate_words[-14:]
        return self._clean(" ".join(draft_words[-42:]))

    def _rebuild_history_memory(self):
        self.history_norm_words = []
        self.recent_history_norm_blocks = []
        for block in self.history:
            norm = self._norm(block)
            if norm:
                self.recent_history_norm_blocks.append(norm)
                self.history_norm_words.extend(norm.split())
        self.history_norm_words = self.history_norm_words[-1400:]
        self.recent_history_norm_blocks = self.recent_history_norm_blocks[-36:]

    def _clear_candidates(self):
        self.candidates = []
        self.last_candidate_words = []
        self.last_candidate_norm_words = []
        self.last_candidate_time = 0.0

    # ------------------------------------------------------------------
    # Text utilities
    # ------------------------------------------------------------------
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

    def _common_prefix_len(self, a, b):
        common = 0
        for x, y in zip(a, b):
            if x == y:
                common += 1
            else:
                break
        return common

    def _suffix_prefix_overlap(self, a, b, max_len=40):
        max_len = min(max_len, len(a), len(b))
        best = 0
        for n in range(1, max_len + 1):
            if a[-n:] == b[:n]:
                best = n
        return best

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
            for n in range(16, 1, -1):
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
