# Changelog

## v0.1.1 - Stabilizer polish

- Przebudowano logikę stabilizacji napisów na podejście candidate-based.
- Publiczny tekst nie jest już budowany przez proste dopisywanie kolejnych fragmentów Whispera.
- Po pauzie zatwierdzana jest ostatnia pełna hipoteza, żeby ograniczyć zjadanie końcówek zdań.
- Poprawiono odcinanie echa historii z rolling-contextu.
- Zmniejszono ryzyko powtórzeń typu „Naszym celem... Naszym celem...”.
- Wydłużono dopuszczalny aktualny blok, żeby wypowiedzi nie były dzielone zbyt szybko.

## v0.1.0 - Clean stable base

- Operator window + audience window.
- Faster-Whisper with CPU/GPU selection.
- Audio input selector.
- Conference-style audience display.
- Operator draft preview.
