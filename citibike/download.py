import hashlib
import json
import shutil
import time
from pathlib import Path, PurePosixPath
import zipfile
import requests
from .settings import ARCHIVE, CSV_DIR, DATA, MIN_BYTES, SOURCE_URL


def download():
    ARCHIVE.parent.mkdir(parents=True, exist_ok=True)
    partial = ARCHIVE.with_suffix(".zip.part")
    with requests.Session() as session:
        head = session.head(SOURCE_URL, timeout=60)
        head.raise_for_status()
        expected = int(head.headers["Content-Length"])
        etag = head.headers.get("ETag", "")
        info_path = ARCHIVE.with_suffix(".download.json")
        old = json.loads(info_path.read_text(encoding="utf-8")) if info_path.exists() else {}
        if ARCHIVE.exists():
            if ARCHIVE.stat().st_size == expected and old.get("etag") == etag:
                print(f"Archiwum już pobrane ({expected / 1e9:.2f} GB).", flush=True)
                return ARCHIVE
            raise RuntimeError("Istniejące archiwum ma inny rozmiar lub ETag.")
        if partial.exists() and old.get("etag") != etag:
            raise RuntimeError("Plik źródłowy zmienił się od rozpoczęcia pobierania. Usuń plik .part.")
        info_path.write_text(json.dumps({"url": SOURCE_URL, "etag": etag, "bytes": expected}, indent=2), encoding="utf-8")
        if shutil.disk_usage(DATA).free < max(expected - (partial.stat().st_size if partial.exists() else 0), 0) + 2_000_000_000:
            raise RuntimeError("Za mało wolnego miejsca na dysku.")
        for attempt in range(1, 7):
            offset = partial.stat().st_size if partial.exists() else 0
            if offset == expected:
                break
            if offset > expected:
                raise RuntimeError("Plik .part jest większy niż archiwum docelowe.")
            headers = {"Range": f"bytes={offset}-", "If-Range": etag} if offset else {}
            try:
                with session.get(SOURCE_URL, headers=headers, stream=True, timeout=(30, 90)) as response:
                    response.raise_for_status()
                    if offset and (response.status_code != 206 or not response.headers.get("Content-Range", "").startswith(f"bytes {offset}-")):
                        raise RuntimeError("Serwer nie obsługuje wznawiania pobierania (Range).")
                    done = offset
                    last = time.monotonic()
                    with partial.open("ab" if offset else "wb") as target:
                        for chunk in response.iter_content(2 * 1024 * 1024):
                            target.write(chunk)
                            done += len(chunk)
                            if time.monotonic() - last > 10:
                                print(f"Pobieranie: {done / 1e9:.2f}/{expected / 1e9:.2f} GB ({100 * done / expected:.0f}%)", flush=True)
                                last = time.monotonic()
                if partial.stat().st_size != expected:
                    raise requests.ConnectionError("Niepełne archiwum")
                break
            except requests.RequestException as exc:
                if attempt == 6:
                    raise
                print(f"Błąd połączenia ({type(exc).__name__}), ponawianie...", flush=True)
                time.sleep(min(attempt * 2, 10))
        partial.replace(ARCHIVE)
        with ARCHIVE.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        info_path.write_text(json.dumps({"url": SOURCE_URL, "etag": etag, "bytes": expected, "sha256": digest}, indent=2), encoding="utf-8")
        print(f"Pobrano {expected:,} bajtów (SHA-256: {digest[:12]}...).", flush=True)
    return ARCHIVE


def _members(archive):
    for member in archive.infolist():
        if "\\" in member.filename or ":" in member.filename:
            raise ValueError("Niedozwolona ścieżka w archiwum")
        parts = PurePosixPath(member.filename).parts
        if member.is_dir() or "__MACOSX" in parts or any(p.startswith(".") for p in parts):
            continue
        if ".." in parts or PurePosixPath(member.filename).is_absolute():
            raise ValueError("Niebezpieczna ścieżka w archiwum")
        yield member


def _copy_member(archive, member, destination):
    if destination.exists() and destination.stat().st_size == member.file_size:
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(destination.parent).free < member.file_size + 2_000_000_000:
        raise RuntimeError("Za mało wolnego miejsca na wypakowanie danych.")
    part = destination.with_suffix(destination.suffix + ".part")
    with archive.open(member) as source, part.open("wb") as target:
        shutil.copyfileobj(source, target, length=2 * 1024 * 1024)
    if part.stat().st_size != member.file_size:
        raise RuntimeError("Niepoprawny rozmiar wypakowanego pliku")
    part.replace(destination)


def extract():
    if not ARCHIVE.exists():
        raise RuntimeError("Brak archiwum. Uruchom najpierw polecenie download.")
    CSV_DIR.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(ARCHIVE) as annual:
        for outer in _members(annual):
            name = PurePosixPath(outer.filename).name
            if name.lower().endswith(".csv"):
                _copy_member(annual, outer, CSV_DIR / name)
            elif name.lower().endswith(".zip"):
                month = DATA / "staging" / name
                marker = CSV_DIR / (name + ".complete.json")
                if marker.exists():
                    items = json.loads(marker.read_text(encoding="utf-8"))
                    if all((CSV_DIR / x["name"]).exists() and (CSV_DIR / x["name"]).stat().st_size == x["bytes"] for x in items):
                        continue
                print(f"Rozpakowywanie {name}...", flush=True)
                _copy_member(annual, outer, month)
                entries = []
                with zipfile.ZipFile(month) as monthly:
                    for inner in _members(monthly):
                        if inner.filename.lower().endswith(".csv"):
                            target = CSV_DIR / PurePosixPath(inner.filename).name
                            _copy_member(monthly, inner, target)
                            entries.append({"name": target.name, "bytes": inner.file_size, "crc32": inner.CRC})
                if not entries:
                    raise RuntimeError(f"Brak plików CSV w {name}")
                marker.write_text(json.dumps(entries, indent=2), encoding="utf-8")
                month.unlink()
    return inventory()


def inventory():
    files = [{"name": p.name, "bytes": p.stat().st_size} for p in sorted(CSV_DIR.glob("*.csv"))]
    total = sum(p["bytes"] for p in files)
    result = {
        "source_url": SOURCE_URL,
        "files": files,
        "csv_count": len(files),
        "uncompressed_csv_bytes": total,
        "minimum_bytes": MIN_BYTES,
        "meets_5gb": total >= MIN_BYTES,
        "gb": total / 1e9,
        "gib": total / 1024**3,
    }
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "manifest.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"Pliki CSV: {len(files)} ({total / 1e9:.3f} GB / {total / 1024**3:.3f} GiB).", flush=True)
    return result

