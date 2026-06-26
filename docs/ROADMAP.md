# CaptionBox AV — Roadmap

## Cel projektu

CaptionBox AV ma być lokalnym, prostym w obsłudze narzędziem dla realizatorów AV do wyświetlania napisów na żywo po polsku na ekranie publiczności.

Priorytety:

- działanie offline,
- niskie opóźnienie,
- stabilne napisy bez migania i powtórek,
- osobne okno operatora i publiczności,
- obsługa wejść audio z miksera/interfejsu,
- CPU fallback oraz NVIDIA CUDA,
- przygotowanie pod diarization.

## v2.0 — wersja bazowa

- [x] Wybór źródła audio
- [x] Wybór CPU/GPU
- [x] Wybór modelu Whisper
- [x] Okno operatora
- [x] Okno publiczności
- [x] Roboczy tekst dla operatora
- [x] Zatwierdzone napisy dla publiczności

## v2.1 — stabilizacja napisów

- [ ] Stabilizer oparty o wspólny prefiks kolejnych hipotez
- [ ] Zatwierdzanie końcówki wypowiedzi po pauzie
- [ ] Ograniczenie powtórek poprzednich fragmentów
- [ ] Oddzielenie historii od aktualnej wypowiedzi

## v2.2 — renderer konferencyjny

- [ ] Historia jako bloki wypowiedzi
- [ ] Aktualna wypowiedź na dole
- [ ] Starsze bloki płyną do góry i znikają poza ekranem
- [ ] Regulowana czcionka publiczności
- [ ] Profile widoku: TV, projektor, LED wall

## v2.3 — ustawienia i profile

- [ ] Zapisywanie ustawień do pliku JSON
- [ ] Automatyczne przywracanie ostatniego wejścia audio
- [ ] Profile: Low Latency, Balanced, Accuracy
- [ ] Skróty klawiszowe operatora

## v3.0 — diarization i mówcy

- [ ] Rozpoznawanie mówców
- [ ] Ręczne nazwy mówców
- [ ] Kolory mówców
- [ ] Eksport transkrypcji po wydarzeniu
