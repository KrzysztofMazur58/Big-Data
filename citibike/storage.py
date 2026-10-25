import os
from pathlib import Path
import shutil
import subprocess
import time
from pymongo import MongoClient
from pymongo.errors import PyMongoError
from .settings import MONGO_URI, MONGO_CACHE_GB, RUNTIME


def client():
    return MongoClient(MONGO_URI, serverSelectionTimeoutMS=2500, tz_aware=True)


def ensure_mongo():
    connection = client()
    try:
        connection.admin.command("ping")
        return connection
    except PyMongoError:
        connection.close()
    if MONGO_URI != "mongodb://127.0.0.1:27018":
        raise RuntimeError("Nie można połączyć się z CITIBIKE_MONGO_URI.")
    executable = shutil.which("mongod")
    if not executable and os.name == "nt":
        candidates = sorted(Path("C:/Program Files/MongoDB/Server").glob("*/bin/mongod.exe"), reverse=True)
        executable = str(candidates[0]) if candidates else None
    if not executable:
        raise RuntimeError("Nie znaleziono mongod. Uruchom kontener/serwer MongoDB lub ustaw CITIBIKE_MONGO_URI.")
    dbpath = RUNTIME / "mongodb"
    if not 0.25 <= MONGO_CACHE_GB <= 4:
        raise RuntimeError("CITIBIKE_MONGO_CACHE_GB musi mieścić się w zakresie 0.25–4 GB.")
    dbpath.mkdir(parents=True, exist_ok=True)
    args = [executable, "--dbpath", str(dbpath), "--port", "27018", "--bind_ip", "127.0.0.1",
            "--wiredTigerCacheSizeGB", str(MONGO_CACHE_GB), "--logpath", str(RUNTIME / "mongodb.log"), "--logappend"]
    proc = subprocess.Popen(args, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    (RUNTIME / "mongodb.pid").write_text(str(proc.pid), encoding="ascii")
    for _ in range(30):
        connection = client()
        try:
            connection.admin.command("ping")
            print(f"Uruchomiono lokalne MongoDB na porcie 27018 (cache {MONGO_CACHE_GB:g} GB).", flush=True)
            return connection
        except PyMongoError:
            connection.close()
            if proc.poll() is not None:
                break
            time.sleep(1)
    raise RuntimeError(f"Nie udało się uruchomić MongoDB. Logi: {RUNTIME / 'mongodb.log'}")

