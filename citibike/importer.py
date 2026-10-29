from collections import Counter, deque
from concurrent.futures import ThreadPoolExecutor
import csv
from datetime import datetime, timezone
import itertools
import time
from pymongo.errors import BulkWriteError
from .cleaning import POLICY_VERSION, REQUIRED_COLUMNS, clean_row
from .settings import CSV_DIR


def insert_batch(collection, documents):
    if not documents:
        return 0, 0
    try:
        collection.insert_many(documents, ordered=False)
        return len(documents), 0
    except BulkWriteError as exc:
        details = exc.details
        if details.get("writeConcernErrors") or any(e["code"] != 11000 for e in details.get("writeErrors", [])):
            raise
        return details["nInserted"], len(details.get("writeErrors", []))


def import_files(db, limit=None, csv_dir=CSV_DIR, batch_size=15000, mode="full"):
    from .locking import database_lock
    with database_lock(db):
        return _import_files(db, limit, csv_dir, batch_size, mode)


def _import_files(db, limit, csv_dir, batch_size, mode):
    files = sorted(csv_dir.glob("*.csv"))
    if not files:
        raise RuntimeError("Brak plików CSV do importu. Wykonaj najpierw download i extract.")
    run = db.metadata.find_one({"_id": "dataset"})
    source_files = [{"name": p.name, "bytes": p.stat().st_size} for p in files]
    if run and (run.get("mode") != mode or run.get("limit") != limit or run.get("policy_version") != POLICY_VERSION):
        raise RuntimeError("Baza zawiera dane z innego trybu importu. Wskaż inną bazę docelową.")
    if run and run.get("source_files") != source_files:
        raise RuntimeError("Lista plików CSV uległa zmianie względem zapisanego stanu w bazie.")
    for path in files:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            headers = next(csv.reader(stream), [])
            if not REQUIRED_COLUMNS.issubset(headers) or len(headers) != len(set(headers)):
                raise RuntimeError(f"Nieprawidłowy nagłówek CSV: {path.name}")
    db.metadata.update_one(
        {"_id": "dataset"},
        {
            "$set": {
                "mode": mode,
                "limit": limit,
                "policy_version": POLICY_VERSION,
                "source_files": source_files,
                "status": "importing",
                "updated_at": datetime.now(timezone.utc),
            },
            "$setOnInsert": {"created_at": datetime.now(timezone.utc)},
        },
        upsert=True,
    )
    total_seen = 0
    session_rows = 0
    started = time.monotonic()
    last = started
    for path in files:
        if limit is not None and total_seen >= limit:
            break
        signature = {"bytes": path.stat().st_size, "mtime_ns": str(path.stat().st_mtime_ns)}
        checkpoint = db.imports.find_one({"_id": path.name})
        if checkpoint and checkpoint["signature"] != signature:
            raise RuntimeError(f"Plik {path.name} został zmodyfikowany od ostatniego importu.")
        counts = Counter(checkpoint.get("counts", {})) if checkpoint else Counter()
        position = checkpoint.get("position", 0) if checkpoint else 0
        total_seen += position
        if checkpoint and checkpoint.get("complete"):
            print(f"Pomijanie {path.name} (już zaimportowano {position:,} wierszy).", flush=True)
            continue
        if limit is not None and total_seen >= limit:
            break
        print(f"Import {path.name} (od wiersza {position:,})...", flush=True)

        pending_writes = deque()
        committed_inserted = counts["inserted"]
        committed_duplicates = counts["duplicate_write_attempts"]

        def commit_oldest():
            nonlocal committed_inserted, committed_duplicates
            future, saved_counts, saved_position, complete = pending_writes.popleft()
            inserted, duplicates = future.result()
            committed_inserted += inserted
            committed_duplicates += duplicates
            saved_counts["inserted"] = committed_inserted
            saved_counts["duplicate_write_attempts"] = committed_duplicates
            counts["inserted"] = committed_inserted
            counts["duplicate_write_attempts"] = committed_duplicates
            db.imports.replace_one(
                {"_id": path.name},
                {
                    "_id": path.name,
                    "signature": signature,
                    "position": saved_position,
                    "counts": saved_counts,
                    "complete": complete,
                    "updated_at": datetime.now(timezone.utc),
                },
                upsert=True,
            )

        def flush(documents, complete=False):
            future = pool.submit(insert_batch, db.trips, documents)
            pending_writes.append((future, dict(counts), position, complete))
            if len(pending_writes) >= 6:
                commit_oldest()

        with ThreadPoolExecutor(max_workers=4) as pool, path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if position:
                next(itertools.islice(reader, position, position), None)
            documents = []
            pending = 0
            exhausted = True
            for row in reader:
                if limit is not None and total_seen >= limit:
                    exhausted = False
                    break
                doc, reason = clean_row(row)
                position += 1
                total_seen += 1
                session_rows += 1
                pending += 1
                counts["read"] += 1
                if reason:
                    counts["rejected"] += 1
                    counts["reject_" + reason] += 1
                else:
                    counts["valid"] += 1
                    if doc["start_station_id"] is None:
                        counts["missing_start_station"] += 1
                    if doc["end_station_id"] is None:
                        counts["missing_end_station"] += 1
                    documents.append(doc)
                if pending >= batch_size:
                    flush(documents)
                    documents = []
                    pending = 0
                if time.monotonic() - last >= 15:
                    rate = session_rows / max(time.monotonic() - started, 1)
                    print(f"Przetworzono {total_seen:,} wierszy ({rate:,.0f} wierszy/s)...", flush=True)
                    last = time.monotonic()
            flush(documents, complete=exhausted)
            while pending_writes:
                commit_oldest()
    db.metadata.update_one(
        {"_id": "dataset"},
        {"$set": {"status": "complete", "updated_at": datetime.now(timezone.utc)}},
    )
    totals = Counter()
    for item in db.imports.find():
        totals.update(item["counts"])
    print(
        f"Import zakończony: odczytano {totals['read']:,}, odrzucono {totals['rejected']:,}, zapisano {totals['inserted']:,}.",
        flush=True,
    )
    return dict(totals)

