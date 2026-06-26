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

## v0.1.2 - Operator LIVE UI polish
- Dodano wyraźny status LIVE / STOP w panelu operatora.
- START jest zielony, gdy program jest zatrzymany.
- STOP jest czerwony, gdy transkrypcja działa.
- Dodano migającą kontrolkę LIVE.
- Dodano prosty pasek poziomu wejścia audio na podstawie RMS.
- Panel operatora pokazuje aktywny model i tryb CPU/GPU.

## v0.2.0 - Word Stabilizer

- Dodano stabilizator oparty o porównywanie słów, a nie sklejanie stringów.
- Mocniejsze odcinanie historii z rolling-contextu Whispera.
- Lepsze scalanie powtórzonych bloków historii.
- Po pauzie zatwierdzana jest pełna ostatnia hipoteza, żeby nie gubić końcówek zdań.
- Dłuższy blok aktualnej wypowiedzi przed automatycznym przejściem do historii.
