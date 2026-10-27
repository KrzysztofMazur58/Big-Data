import argparse
import json
import shutil
import sys
from pymongo.errors import PyMongoError
from .settings import DATA, FULL_DATABASE, SAMPLE_DATABASE


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Analiza danych przejazdów Citi Bike NYC (2023)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="Sprawdź połączenie z bazą MongoDB i wolne miejsce na dysku")
    sub.add_parser("download", help="Pobierz roczne archiwum danych (ok. 1,6 GB)")
    sub.add_parser("extract", help="Rozpakuj archiwum i pliki CSV")
    sub.add_parser("inventory", help="Podsumuj rozmiar rozpakowanych plików CSV")
    demo = sub.add_parser("demo", help="Uruchom potok przetwarzania na próbce danych")
    demo.add_argument("--limit", type=int, default=100_000, help="Limit wierszy dla próbki")
    sub.add_parser("full", help="Uruchom potok przetwarzania na pełnym zbiorze danych")
    sub.add_parser("package", help="Utwórz archiwum ZIP z kodem i wynikami")
    for name in ("import", "analyze", "status"):
        cmd = sub.add_parser(
            name,
            help={
                "import": "Importuj pliki CSV do bazy MongoDB",
                "analyze": "Oblicz statystyki i wygeneruj raporty",
                "status": "Wyświetl status importu i bazy danych",
            }[name],
        )
        cmd.add_argument("--database", default=FULL_DATABASE)
    args = parser.parse_args()
    try:
        run(args)
    except (RuntimeError, ValueError, OSError, PyMongoError) as exc:
        print(f"Błąd: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Przerwano działanie programu.")
        return 130
    return 0


def run(args):
    from .download import download, extract, inventory

    if args.command == "package":
        from .package import package
        package()
        return
    if args.command == "download":
        download()
        return
    if args.command == "extract":
        extract()
        return
    if args.command == "inventory":
        inventory()
        return
    if args.command == "demo" and args.limit <= 0:
        raise ValueError("Limit wierszy musi być większy od zera.")

    from .storage import ensure_mongo

    with ensure_mongo() as connection:
        if args.command == "doctor":
            version = connection.server_info()["version"]
            free_gb = shutil.disk_usage(DATA.parent).free / 1e9
            print(f"Python: {sys.version.split()[0]} | MongoDB: {version} | Wolne miejsce: {free_gb:.1f} GB")
            return

        from .importer import import_files
        from .analysis import analyze

        database = getattr(args, "database", SAMPLE_DATABASE if args.command == "demo" else FULL_DATABASE)
        db = connection[database]

        if args.command == "status":
            status_data = {
                "database": database,
                "metadata": db.metadata.find_one({"_id": "dataset"}),
                "estimated_trips": db.trips.estimated_document_count(),
                "completed_csv": db.imports.count_documents({"complete": True}),
                "started_csv": db.imports.count_documents({}),
            }
            print(json.dumps(status_data, ensure_ascii=False, indent=2, default=str))
            return

        if args.command in {"demo", "full"}:
            download()
            manifest = extract()
            if args.command == "full" and not manifest["meets_5gb"]:
                raise RuntimeError("Rozmiar rozpakowanych plików CSV jest mniejszy niż 5 GB.")
            import_files(
                db,
                limit=args.limit if args.command == "demo" else None,
                mode="sample" if args.command == "demo" else "full",
            )
        elif args.command == "import":
            manifest = inventory()
            if not manifest["meets_5gb"]:
                raise RuntimeError("Rozmiar rozpakowanych plików CSV jest mniejszy niż 5 GB.")
            import_files(db)
            return

        analyze(db)


if __name__ == "__main__":
    sys.exit(main())

