import json
from datetime import datetime, timezone
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pymongo import ReplaceOne
from .settings import OUTPUT

WEEKDAYS = ["Poniedziałek", "Wtorek", "Środa", "Czwartek", "Piątek", "Sobota", "Niedziela"]
USER_LABELS = {"member": "Z abonamentem", "casual": "Bez abonamentu"}


def analyze(db, output_dir=None):
    meta = db.metadata.find_one({"_id": "dataset"})
    if not meta or meta.get("status") != "complete":
        raise RuntimeError("Import danych nie został jeszcze ukończony.")
    output_dir = Path(output_dir) if output_dir else OUTPUT / ("demo" if meta["mode"] == "sample" else "full")
    output_dir.mkdir(parents=True, exist_ok=True)
    print("Wykonywanie agregacji w MongoDB...", flush=True)
    pipelines = {
        "summary": [
            {
                "$group": {
                    "_id": None,
                    "count": {"$sum": 1},
                    "mean_minutes": {"$avg": {"$divide": ["$duration_seconds", 60]}},
                    "min_started_at": {"$min": "$started_at_local"},
                    "max_started_at": {"$max": "$started_at_local"},
                    "missing_start_station": {
                        "$sum": {"$cond": [{"$eq": ["$start_station_id", None]}, 1, 0]}
                    },
                }
            }
        ],
        "hours": [{"$group": {"_id": "$start_hour", "count": {"$sum": 1}}}, {"$sort": {"_id": 1}}],
        "weekdays": [{"$group": {"_id": "$start_weekday", "count": {"$sum": 1}}}, {"$sort": {"_id": 1}}],
        "months": [{"$group": {"_id": "$start_month", "count": {"$sum": 1}}}, {"$sort": {"_id": 1}}],
        "users": [
            {
                "$group": {
                    "_id": "$member_casual",
                    "count": {"$sum": 1},
                    "mean_minutes": {"$avg": {"$divide": ["$duration_seconds", 60]}},
                    "stddev_minutes": {"$stdDevPop": {"$divide": ["$duration_seconds", 60]}},
                }
            },
            {"$sort": {"_id": 1}},
        ],
        "stations": [
            {"$match": {"start_station_id": {"$ne": None}}},
            {
                "$group": {
                    "_id": "$start_station_id",
                    "name": {"$min": "$start_station_name"},
                    "count": {"$sum": 1},
                }
            },
            {"$sort": {"count": -1, "_id": 1}},
            {"$limit": 10},
        ],
    }
    values = next(db.trips.aggregate([{"$facet": pipelines}], allowDiskUse=True), None)
    if not values or not values["summary"]:
        raise RuntimeError("Brak rekordów w kolekcji trips.")
    values["summary"] = values["summary"][0]
    del values["summary"]["_id"]
    values["mode"] = meta["mode"]
    values["database"] = db.name
    values["generated_at"] = datetime.now(timezone.utc).isoformat()
    values["import_files"] = [
        {
            "file": item["_id"],
            "position": item["position"],
            "counts": item["counts"],
            "complete": item["complete"],
        }
        for item in db.imports.find().sort("_id", 1)
    ]
    db.results.bulk_write(
        [ReplaceOne({"_id": key}, {"_id": key, "data": value}, upsert=True) for key, value in values.items()]
    )
    (output_dir / "wyniki.json").write_text(json.dumps(values, ensure_ascii=False, indent=2), encoding="utf-8")
    plot(values, output_dir)
    print(f"Zapisano wyniki w {output_dir} (liczba przejazdów: {values['summary']['count']:,}).", flush=True)
    return values, output_dir


def plot(values, directory):
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 11,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "figure.facecolor": "white",
            "axes.titleweight": "bold",
        }
    )
    suffix = "Citi Bike NYC 2023 (próbka)" if values["mode"] == "sample" else "Citi Bike NYC 2023"
    for key, domain, labels, title, filename in [
        ("hours", list(range(24)), [str(x) for x in range(24)], "Liczba przejazdów według godziny rozpoczęcia", "01_godziny.png"),
        ("weekdays", list(range(7)), WEEKDAYS, "Liczba przejazdów według dnia tygodnia", "02_dni_tygodnia.png"),
    ]:
        lookup = {r["_id"]: r["count"] for r in values[key]}
        fig, ax = plt.subplots(figsize=(11, 5.5), layout="constrained")
        ax.bar(labels, [lookup.get(x, 0) for x in domain], color="#126782")
        ax.set(
            title=f"{title}\n{suffix}",
            ylabel="Liczba przejazdów",
            xlabel="Godzina (America/New_York)" if key == "hours" else "Dzień tygodnia",
        )
        if key == "weekdays":
            ax.tick_params(axis="x", labelrotation=20)
        ax.ticklabel_format(axis="y", style="plain")
        ax.grid(axis="y", alpha=0.18)
        fig.savefig(directory / filename, dpi=160)
        plt.close(fig)

    fig, ax = plt.subplots(figsize=(9, 5.5), layout="constrained")
    bars = ax.bar(
        [USER_LABELS.get(x["_id"], x["_id"]) for x in values["users"]],
        [x["mean_minutes"] for x in values["users"]],
        color=["#e09f3e", "#126782"][: len(values["users"])],
    )
    ax.bar_label(bars, fmt="%.2f min", padding=4)
    ax.margins(y=0.15)
    ax.set(title=f"Średni czas przejazdu według typu użytkownika\n{suffix}", ylabel="Minuty")
    fig.savefig(directory / "03_czas_jazdy.png", dpi=160)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(12, 7), layout="constrained")
    stations = list(reversed(values["stations"]))
    ax.barh([str(x["name"] or x["_id"]) for x in stations], [x["count"] for x in stations], color="#126782")
    ax.set(title=f"10 najpopularniejszych stacji początkowych\n{suffix}", xlabel="Liczba rozpoczętych przejazdów")
    fig.savefig(directory / "04_stacje.png", dpi=160)
    plt.close(fig)

    save_html(values, directory)


def save_html(values, directory):
    n = f"{values['summary']['count']:,}".replace(",", " ")
    mean_min = values["summary"]["mean_minutes"]
    scope = "Próbka (100 000 wierszy)" if values["mode"] == "sample" else "Pełny zbiór 2023"
    figures = "".join(
        f'<figure><img src="{name}" alt="{label}"><figcaption>{label}</figcaption></figure>'
        for name, label in [
            ("01_godziny.png", "Liczba przejazdów według godziny rozpoczęcia"),
            ("02_dni_tygodnia.png", "Liczba przejazdów według dnia tygodnia"),
            ("03_czas_jazdy.png", "Średni czas przejazdu według typu użytkownika"),
            ("04_stacje.png", "10 najpopularniejszych stacji początkowych"),
        ]
    )
    user_rows = "".join(
        f"<tr><td>{USER_LABELS.get(u['_id'], u['_id'])}</td><td>{u['count']:,}</td><td>{u['mean_minutes']:.2f} min</td><td>{u['stddev_minutes']:.2f} min</td></tr>".replace(",", " ")
        for u in values["users"]
    )
    station_rows = "".join(
        f"<tr><td>{i + 1}</td><td>{s['name'] or s['_id']}</td><td>{s['_id']}</td><td>{s['count']:,}</td></tr>".replace(",", " ")
        for i, s in enumerate(values["stations"])
    )
    page = f"""<!doctype html><html lang="pl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Citi Bike NYC 2023 – wyniki analizy</title>
<style>
body{{font:16px/1.6 system-ui,sans-serif;max-width:1060px;margin:40px auto;padding:0 24px;color:#18313d;background:#f6f8fa}}
h1,h2{{line-height:1.2}}
.scope{{padding:14px;background:#dcefe8;border-left:5px solid #126782}}
.stats{{display:flex;gap:32px;flex-wrap:wrap;margin:24px 0}}
.stats b{{display:block;font-size:28px}}
figure{{margin:24px 0;padding:16px;background:white;border:1px solid #dce2e5}}
img{{width:100%;height:auto}}
table{{width:100%;border-collapse:collapse;background:white;margin:16px 0;border:1px solid #dce2e5}}
th,td{{padding:10px 14px;text-align:left;border-bottom:1px solid #dce2e5}}
th{{background:#dce9ee}}
a{{color:#126782}}
</style>
<h1>Analiza przejazdów Citi Bike NYC (2023)</h1>
<p class="scope"><b>Zakres:</b> {scope} | <b>Baza:</b> {values['database']}</p>
<div class="stats">
  <div><b>{n}</b>przeanalizowanych przejazdów</div>
  <div><b>{mean_min:.2f} min</b>średni czas jazdy</div>
</div>
<p><a href="wyniki.json">Pobierz surowe wyniki (wyniki.json)</a></p>
<h2>Zestawienie według typu użytkownika</h2>
<table><thead><tr><th>Typ użytkownika</th><th>Liczba przejazdów</th><th>Średni czas</th><th>Odchylenie std.</th></tr></thead><tbody>{user_rows}</tbody></table>
<h2>Top 10 stacji początkowych</h2>
<table><thead><tr><th>#</th><th>Stacja</th><th>ID</th><th>Liczba przejazdów</th></tr></thead><tbody>{station_rows}</tbody></table>
<h2>Wykresy</h2>
{figures}
</html>"""
    (directory / "wyniki.html").write_text(page, encoding="utf-8")


