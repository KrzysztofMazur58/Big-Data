import csv
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
import uuid
import zipfile

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from citibike.cleaning import REQUIRED_COLUMNS, clean_row


def row(ride_id="A000000000000001", start="2023-01-02 08:00:00", end="2023-01-02 08:10:00", user="member", station="S1"):
    return dict(
        ride_id=ride_id,
        rideable_type="classic_bike",
        started_at=start,
        ended_at=end,
        member_casual=user,
        start_station_name="Testowa " + station,
        start_station_id=station,
        end_station_name="Koniec",
        end_station_id="S3",
        start_lat="40.7",
        start_lng="-74",
        end_lat="40.8",
        end_lng="-73.9",
    )


class DataQualityTests(unittest.TestCase):
    def test_archive_path_validation(self):
        from citibike.download import _members

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("C:\\outside.csv", "data")
        with zipfile.ZipFile(buffer) as archive:
            with self.assertRaises(ValueError):
                list(_members(archive))

    def test_duration_across_spring_dst(self):
        document, reason = clean_row(row(start="2023-03-12 01:50:00", end="2023-03-12 03:10:00"))
        self.assertIsNone(reason)
        self.assertEqual(document["duration_seconds"], 1200)
        self.assertEqual(document["start_hour"], 1)

    def test_ambiguous_fall_dst_rejected(self):
        document, reason = clean_row(row(start="2023-11-05 01:10:00", end="2023-11-05 02:10:00"))
        self.assertIsNone(document)
        self.assertEqual(reason, "niepoprawny_lub_niejednoznaczny_czas")

    def test_negative_duration_and_missing_station(self):
        self.assertEqual(clean_row(row(end="2023-01-02 07:59:59"))[1], "czas_niedodatni")
        values = row()
        values["start_station_id"] = ""
        values["start_lat"] = ""
        document, reason = clean_row(values)
        self.assertIsNone(reason)
        self.assertIsNone(document["start_station_id"])
        self.assertIsNone(document["start_lat"])

    def test_nonfinite_coordinate_rejected(self):
        values = row()
        values["start_lat"] = "NaN"
        self.assertEqual(clean_row(values)[1], "niepoprawne_wspolrzedne")


@unittest.skipUnless(os.environ.get("CITIBIKE_TEST_MONGO") == "1", "Wymaga działającej instancji MongoDB")
class MongoIntegrationTests(unittest.TestCase):
    def test_pipeline_import_and_aggregation(self):
        from citibike.storage import ensure_mongo
        from citibike.importer import import_files
        from citibike.analysis import analyze
        from citibike.locking import database_lock

        connection = ensure_mongo()
        database_name = "citibike_test_" + uuid.uuid4().hex
        db = connection[database_name]
        try:
            with tempfile.TemporaryDirectory() as temp:
                directory = Path(temp)
                fixtures = [
                    row(),
                    row("A000000000000002", end="2023-01-02 08:30:00"),
                    row("A000000000000003", end="2023-01-02 08:40:00", user="casual", station="S2"),
                    row(),
                    row("A000000000000004", end="2023-01-02 07:59:00"),
                ]
                with (directory / "fixture.csv").open("w", encoding="utf-8", newline="") as out:
                    writer = csv.DictWriter(out, fieldnames=sorted(REQUIRED_COLUMNS))
                    writer.writeheader()
                    writer.writerows(fixtures)

                counts = import_files(db, csv_dir=directory, batch_size=2, mode="sample")
                self.assertEqual(counts["read"], 5)
                self.assertEqual(counts["rejected"], 1)
                self.assertEqual(counts["duplicate_write_attempts"], 1)
                self.assertEqual(db.trips.count_documents({}), 3)

                before = db.imports.find_one()["counts"]
                import_files(db, csv_dir=directory, batch_size=2, mode="sample")
                self.assertEqual(db.trips.count_documents({}), 3)
                self.assertEqual(db.imports.find_one()["counts"], before)

                with database_lock(db):
                    with self.assertRaisesRegex(RuntimeError, "Inny proces importu"):
                        import_files(db, csv_dir=directory, batch_size=2, mode="sample")

                values, output = analyze(db, output_dir=directory / "results")
                self.assertEqual(values["summary"]["count"], 3)
                self.assertAlmostEqual(values["summary"]["mean_minutes"], 80 / 3)
                groups = {x["_id"]: x for x in values["users"]}
                self.assertEqual(groups["member"]["mean_minutes"], 20)
                self.assertEqual(groups["member"]["stddev_minutes"], 10)
                self.assertEqual(groups["casual"]["mean_minutes"], 40)
                self.assertEqual(values["stations"][0]["count"], 2)
                self.assertEqual(sum(x["count"] for x in values["hours"]), 3)
                self.assertTrue((output / "wyniki.html").exists())

                db.imports.update_one({}, {"$set": {"complete": False, "position": 0, "counts": {}}})
                import_files(db, csv_dir=directory, batch_size=2, mode="sample")
                self.assertEqual(db.trips.count_documents({}), 3)
        finally:
            connection.drop_database(database_name)
            connection.close()


if __name__ == "__main__":
    unittest.main()

