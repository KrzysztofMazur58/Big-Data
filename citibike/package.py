import json
import zipfile
from .settings import ROOT, OUTPUT, DATA


def package():
    directory = OUTPUT / "full"
    if not (directory / "wyniki.json").exists():
        raise RuntimeError("Brak wyników dla pełnego zbioru w output/full. Uruchom najpierw polecenie full.")
    values = json.loads((directory / "wyniki.json").read_text(encoding="utf-8"))
    manifest = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))
    source_names = {x["name"] for x in manifest["files"]}
    imported_names = {x["file"] for x in values["import_files"]}
    if (
        values["mode"] != "full"
        or not manifest["meets_5gb"]
        or source_names != imported_names
        or not all(x["complete"] for x in values["import_files"])
    ):
        raise RuntimeError("Pełny import wszystkich plików CSV nie został jeszcze ukończony.")
    required_results = [
        "wyniki.json",
        "wyniki.html",
        "01_godziny.png",
        "02_dni_tygodnia.png",
        "03_czas_jazdy.png",
        "04_stacje.png",
    ]
    if any(not (directory / name).exists() for name in required_results):
        raise RuntimeError("Brak wszystkich plików raportu w output/full – uruchom polecenie analyze.")

    base_files = ["README.md", "main.py", "setup.ps1", "projekt.json", "requirements.txt", "requirements-lock.txt", ".gitignore"]
    files = [ROOT / name for name in base_files if (ROOT / name).exists()]
    files += sorted((ROOT / "citibike").glob("*.py")) + sorted((ROOT / "tests").glob("*.py"))
    files += [DATA / "manifest.json"] + sorted((DATA / "downloads").glob("*.download.json"))
    files += [directory / name for name in required_results]

    path = OUTPUT / "projekt_citibike.zip"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for source in files:
            archive.write(source, arcname="projekt_citibike/" + source.relative_to(ROOT).as_posix())
    print(f"Utworzono archiwum: {path} ({path.stat().st_size / 1e6:.2f} MB).", flush=True)
    return path

