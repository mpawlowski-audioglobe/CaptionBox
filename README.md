# CaptionBox AV

Lokalny program do napisów na żywo dla realizatorów AV.

## Uruchomienie

1. Uruchom `setup.bat` przy pierwszej instalacji.
2. Uruchom `run.bat`.
3. Wybierz wejście audio, tryb CPU/GPU, model i rozmiar czcionki.
4. Kliknij `START`.

## Rekomendowane ustawienia

Dla RTX 3070:

- Obliczenia: `GPU / CUDA`
- Model: `medium`
- Czcionka publiczności: `34 px` albo `36 px`

Dla komputera bez NVIDIA:

- Obliczenia: `CPU`
- Model: `small` albo `base`

## v0.1.1

Ta wersja ma poprawiony stabilizator napisów:

- mniej powtórzeń,
- mniej zjadania końcówek,
- lepsze dopisywanie ostatniej hipotezy po pauzie,
- bardziej stabilne zachowanie historii wypowiedzi.
