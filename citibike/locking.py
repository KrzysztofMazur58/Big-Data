from contextlib import contextmanager
import hashlib
import os
from .settings import RUNTIME


@contextmanager
def database_lock(db):
    identity = hashlib.sha256(f"{db.client.address}/{db.name}".encode()).hexdigest()[:20]
    directory = RUNTIME / "locks"
    directory.mkdir(parents=True, exist_ok=True)
    stream = (directory / f"{identity}.lock").open("a+b")
    stream.write(b"\0")
    stream.flush()
    stream.seek(0)
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        stream.close()
        raise RuntimeError("Inny proces importu już korzysta z tej bazy.") from exc
    try:
        yield
    finally:
        stream.seek(0)
        if os.name == "nt":
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        stream.close()

