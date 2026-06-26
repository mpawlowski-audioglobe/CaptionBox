# CaptionBox AV 2.0

Lokalny program do napisów konferencyjnych po polsku.

## Cel wersji

Ta wersja wraca do `faster-whisper` i rezygnuje z Parakeet/NeMo, bo Parakeet na Windows powodował problemy instalacyjne. Zamiast zmieniać silnik ASR, wersja 2.0 dodaje stabilizator napisów:

- operator widzi roboczą hipotezę,
- publiczność widzi tylko stabilniejsze, zatwierdzone słowa,
- krótkie ogony i echa poprzednich kwestii są odrzucane,
- historia jest blokami wypowiedzi,
- aktualna wypowiedź jest na dole,
- historia płynie w górę i znika poza ekranem,
- można wybrać wejście audio, CPU/GPU, model oraz rozmiar czcionki publiczności.

## Instalacja

1. Rozpakuj ZIP.
2. Uruchom `setup.bat`.
3. Po zakończeniu uruchom `run.bat`.

## Zalecane ustawienia dla RTX 3070

- Obliczenia: `GPU / CUDA`
- Model: `medium`
- Czcionka: `34 px` lub `36 px`

## CPU / komputery bez NVIDIA

Program powinien działać na CPU, ale opóźnienie będzie większe. Wtedy wybierz:

- Obliczenia: `CPU`
- Model: `small` albo `base`

## Test

Czytaj tekst testowy normalnym tempem, z krótkimi pauzami pomiędzy akapitami.
