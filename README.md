# Citi Bike NYC 2023 – Analiza danych w MongoDB

Aplikacja do pobierania, czyszczenia, importu oraz analizy statystycznej przejazdów rowerów miejskich sieci **Citi Bike w Nowym Jorku** za rok 2023 (`>6,8 GB` danych CSV po wypakowaniu).

## Autorzy
- Krzysztof Mazur
- Bartosz Oliwiak

## Wymagania
- Python 3.11+
- MongoDB 6.0+ / 7.0+ (uruchomione lokalnie lub w kontenerze Docker na porcie `27018`)

## Szybki start

### 1. Instalacja środowiska
```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```

Jeśli używasz Dockera zamiast lokalnej instalacji MongoDB Community Server:
```powershell
docker run -d --name citibike-mongo -p 127.0.0.1:27018:27017 -v "${PWD}\.runtime\mongodb:/data/db" mongo:7 --wiredTigerCacheSizeGB 1
```

### 2. Dostępne polecenia CLI (`main.py`)
```powershell
# Sprawdzenie połączenia z MongoDB i miejsca na dysku
.\.venv\Scripts\python.exe main.py doctor

# Pobranie archiwum rocznego (ok. 1,6 GB) i rozpakowanie plików CSV (6,87 GB)
.\.venv\Scripts\python.exe main.py download
.\.venv\Scripts\python.exe main.py extract

# Przebieg testowy na próbce 100 000 wierszy (baza: citibike_demo, wyniki: output/demo/)
.\.venv\Scripts\python.exe main.py demo

# Pełny przebieg dla całego rocznika 2023 (baza: citibike_2023, wyniki: output/full/)
.\.venv\Scripts\python.exe main.py full

# Sprawdzenie statusu bazy i postępu importu
.\.venv\Scripts\python.exe main.py status
```

## Struktura projektu
- `main.py` – punkt wejścia aplikacji CLI
- `citibike/settings.py` – konfiguracja ścieżek, adresów URL oraz parametrów bazy
- `citibike/download.py` – strumieniowe pobieranie archiwum ZIP i rozpakowywanie plików CSV
- `citibike/cleaning.py` – walidacja wierszy, konwersja stref czasowych (`America/New_York` -> `UTC`)
- `citibike/importer.py` – wielowątkowy import paczkami do MongoDB z obsługą wznawiania
- `citibike/analysis.py` – agregacje statystyczne w MongoDB (`$facet`), wykresy `matplotlib` oraz zestawienie HTML/JSON
- `tests/test_project.py` – testy jednostkowe i integracyjne
