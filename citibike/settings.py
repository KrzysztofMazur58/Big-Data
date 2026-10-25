import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
ARCHIVE = DATA / "downloads" / "2023-citibike-tripdata.zip"
CSV_DIR = DATA / "csv"
OUTPUT = ROOT / "output"
RUNTIME = ROOT / ".runtime"

SOURCE_URL = "https://s3.amazonaws.com/tripdata/2023-citibike-tripdata.zip"
SOURCE_DOCS = "https://citibikenyc.com/system-data"

MONGO_URI = os.environ.get("CITIBIKE_MONGO_URI", "mongodb://127.0.0.1:27018")
MONGO_CACHE_GB = float(os.environ.get("CITIBIKE_MONGO_CACHE_GB", "1"))
MIN_BYTES = 5_000_000_000

SAMPLE_DATABASE = "citibike_demo"
FULL_DATABASE = "citibike_2023"

