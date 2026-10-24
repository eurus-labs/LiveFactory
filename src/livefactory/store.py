"""SQLite store for the core (spec sections 5 and 15, ADR-0010).

The stored `FactoryState` is the source of truth. Each state-changing event is
committed in one transaction with the new state and its outbox messages; core
never rebuilds state by replaying history through whatever reducer version is
running. The `events` table is an append-only audit log of what changed state,
and `audit` keeps rejected and conflicting messages.

One process writes: an exclusive `flock` is held while the store is open. Any
failure while writing makes the store unavailable until it is opened again,
which reloads the committed state (spec section 15.2).
"""

from __future__ import annotations

import fcntl
import importlib.metadata
import os
import sqlite3
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Any, Self

from livefactory.core import codec
from livefactory.core.check import state_violations
from livefactory.core.events import (
    AwaitDecision,
    AwaitRelease,
    Event,
    Outbox,
    RequestReconcile,
    StartAttempt,
    StopAttempt,
    WorkflowEnded,
)
from livefactory.core.model import FactoryState, ReceiptOutcome, empty_state
from livefactory.core.reducer import Transition, apply

SCHEMA_VERSION = 1
_OUTBOX_TYPES = (StartAttempt, StopAttempt, RequestReconcile, AwaitDecision, AwaitRelease, WorkflowEnded)

_SCHEMA = (
    "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    "CREATE TABLE state (id INTEGER PRIMARY KEY CHECK (id = 1), seq INTEGER NOT NULL,"
    " body TEXT NOT NULL)",
    "CREATE TABLE events (seq INTEGER PRIMARY KEY, key TEXT NOT NULL, outcome TEXT NOT NULL,"
    " reason TEXT NOT NULL, body TEXT NOT NULL, received_at TEXT NOT NULL,"
    " core_version TEXT NOT NULL)",
    "CREATE INDEX events_key ON events (key)",
    "CREATE TABLE outbox (id INTEGER PRIMARY KEY, seq INTEGER NOT NULL REFERENCES events (seq),"
    " body TEXT NOT NULL, delivered INTEGER NOT NULL DEFAULT 0)",
    "CREATE TABLE audit (id INTEGER PRIMARY KEY, key TEXT NOT NULL, outcome TEXT NOT NULL,"
    " reason TEXT NOT NULL, body TEXT NOT NULL, received_at TEXT NOT NULL)",
)


class StoreError(Exception):
    pass


class StoreMissing(StoreError):
    """No store exists at the path; create one explicitly."""


class StoreLocked(StoreError):
    """Another process has the store open for writing."""


class StoreUnavailable(StoreError):
    """The store cannot be written now. The last write's outcome may be unknown:
    reopen the store and resend the same event to find out."""


class StoreCorrupt(StoreError):
    """Integrity or state checks failed. Maintenance is needed; do not retry."""


class StoreIncompatible(StoreError):
    """The store has a schema version this code does not handle."""


type Clock = Callable[[], datetime]
type Fault = Callable[[str], None]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _no_fault(point: str) -> None:
    return None


def core_version() -> str:
    try:
        return importlib.metadata.version("livefactory")
    except importlib.metadata.PackageNotFoundError:
        return "0+unknown"


@dataclass(frozen=True)
class EventRecord:
    seq: int
    key: str
    outcome: str
    reason: str
    received_at: str
    core_version: str
    event: Event


@dataclass(frozen=True)
class AuditRecord:
    key: str
    outcome: str
    reason: str
    received_at: str
    event: Event


class Store:
    """Open with `Store.create` or `Store.open`; use as a context manager."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        lock_fd: int,
        state: FactoryState,
        seq: int,
        dev_mode: bool,
        clock: Clock,
        fault: Fault,
    ) -> None:
        self._conn = connection
        self._lock_fd: int | None = lock_fd
        self._state = state
        self._seq = seq
        self._dev_mode = dev_mode
        self._clock = clock
        self._fault = fault
        self._degraded = False
        self._version = core_version()

    # -- opening --------------------------------------------------------------

    @classmethod
    def create(
        cls, path: Path, *, dev_mode: bool = False, clock: Clock = _utc_now, fault: Fault = _no_fault
    ) -> Self:
        """Create a store atomically: a crash leaves no half-made store at `path`."""
        if path.exists():
            raise StoreError(f"{path} already exists")
        lock_fd = _lock(path)
        try:
            # Checked again under the lock: another process may have created
            # it after the first check (only creators and openers take the lock).
            if path.exists():
                raise StoreError(f"{path} already exists")
            _build(path, dev_mode)
            return cls._open_locked(path, lock_fd, clock, fault)
        except BaseException:
            _unlock(lock_fd)
            raise

    @classmethod
    def open(cls, path: Path, *, clock: Clock = _utc_now, fault: Fault = _no_fault) -> Self:
        if not path.exists():
            raise StoreMissing(f"no store at {path}; run `livefactory init` first")
        lock_fd = _lock(path)
        try:
            return cls._open_locked(path, lock_fd, clock, fault)
        except BaseException:
            _unlock(lock_fd)
            raise

    @classmethod
    def _open_locked(cls, path: Path, lock_fd: int, clock: Clock, fault: Fault) -> Self:
        connection: sqlite3.Connection | None = None
        try:
            connection = _connect_existing(path)
            state, seq, dev_mode = _load_checked(connection)
            store = cls(connection, lock_fd, state, seq, dev_mode, clock, fault)
            store._probe()
            return store
        except sqlite3.OperationalError as exc:
            _close_quietly(connection)
            if _transient(exc):
                raise StoreUnavailable(f"{path}: {exc}") from exc
            raise StoreCorrupt(f"{path}: {_short(exc)}") from exc
        except (sqlite3.DatabaseError, ValueError) as exc:  # includes UnicodeDecodeError
            _close_quietly(connection)
            raise StoreCorrupt(f"{path}: {_short(exc)}") from exc
        except BaseException:
            _close_quietly(connection)
            raise

    def close(self) -> None:
        _close_quietly(self._conn)
        if self._lock_fd is not None:
            _unlock(self._lock_fd)
            self._lock_fd = None

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    # -- reading --------------------------------------------------------------

    @property
    def state(self) -> FactoryState:
        return self._state

    @property
    def dev_mode(self) -> bool:
        return self._dev_mode

    def pending_outbox(self) -> list[tuple[int, Outbox]]:
        rows = self._conn.execute(
            "SELECT id, body FROM outbox WHERE delivered = 0 ORDER BY id"
        ).fetchall()
        return [(int(row[0]), _decode(row[1], "outbox message")) for row in rows]

    def events(self) -> list[EventRecord]:
        rows = self._conn.execute(
            "SELECT seq, key, outcome, reason, received_at, core_version, body"
            " FROM events ORDER BY seq"
        ).fetchall()
        return [
            EventRecord(int(r[0]), r[1], r[2], r[3], r[4], r[5], _decode(r[6], "event"))
            for r in rows
        ]

    def audit(self) -> list[AuditRecord]:
        rows = self._conn.execute(
            "SELECT key, outcome, reason, received_at, body FROM audit ORDER BY id"
        ).fetchall()
        return [AuditRecord(r[0], r[1], r[2], r[3], _decode(r[4], "audit record")) for r in rows]

    # -- writing --------------------------------------------------------------

    def submit(self, event: Event) -> Transition:
        """Apply one event; acknowledge only after it is committed."""
        self._require_healthy()
        before = self._state
        transition = apply(before, event)
        received_at = self._clock().isoformat()
        if transition.state is before:
            # Nothing changed. Keep a record of refusals and conflicts (spec
            # T02); they acknowledge nothing, so a failed audit write only
            # marks the store degraded.
            if transition.receipt.outcome in (ReceiptOutcome.REJECTED, ReceiptOutcome.CONFLICT):
                self._write_audit(event, transition, received_at)
            return transition

        try:
            self._conn.execute("BEGIN IMMEDIATE")
            row = self._conn.execute("SELECT seq FROM state WHERE id = 1").fetchone()
            if row is None or int(row[0]) != self._seq:
                raise StoreError("the stored state changed under this process")
            cursor = self._conn.execute(
                "INSERT INTO events (key, outcome, reason, body, received_at, core_version)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    transition.receipt.key,
                    transition.receipt.outcome.value,
                    transition.receipt.reason,
                    codec.dumps(event),
                    received_at,
                    self._version,
                ),
            )
            seq = cursor.lastrowid
            assert seq is not None
            self._conn.executemany(
                "INSERT INTO outbox (seq, body) VALUES (?, ?)",
                [(seq, codec.dumps(message)) for message in transition.outbox],
            )
            self._conn.execute(
                "UPDATE state SET seq = ?, body = ? WHERE id = 1",
                (seq, codec.dumps(transition.state)),
            )
            self._fault("before_commit")
            self._conn.execute("COMMIT")
            self._fault("after_commit")
        except BaseException as exc:
            self._degrade()
            if isinstance(exc, Exception):
                raise StoreUnavailable(f"write failed, outcome may be unknown: {exc}") from exc
            raise
        self._state = transition.state
        self._seq = seq
        return transition

    def mark_delivered(self, outbox_id: int) -> None:
        self._require_healthy()
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            self._conn.execute(
                "UPDATE outbox SET delivered = 1 WHERE id = ? AND delivered = 0", (outbox_id,)
            )
            self._fault("before_commit")
            self._conn.execute("COMMIT")
        except BaseException as exc:
            self._degrade()
            if isinstance(exc, Exception):
                raise StoreUnavailable(f"could not mark {outbox_id} delivered: {exc}") from exc
            raise

    # -- internals --------------------------------------------------------------

    def _require_healthy(self) -> None:
        if self._degraded:
            raise StoreUnavailable("the store is degraded; reopen it before writing")

    def _degrade(self) -> None:
        self._degraded = True
        if self._conn.in_transaction:
            try:
                self._conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass

    def _write_audit(self, event: Event, transition: Transition, received_at: str) -> None:
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            self._conn.execute(
                "INSERT INTO audit (key, outcome, reason, body, received_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    transition.receipt.key,
                    transition.receipt.outcome.value,
                    transition.receipt.reason,
                    codec.dumps(event),
                    received_at,
                ),
            )
            self._fault("before_commit")
            self._conn.execute("COMMIT")
        except Exception:
            self._degrade()

    def _probe(self) -> None:
        """A small write, so an unwritable store fails at open (INV-10)."""
        self._conn.execute("BEGIN IMMEDIATE")
        self._conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('last_open', ?)",
            (self._clock().isoformat(),),
        )
        self._fault("probe")
        self._conn.execute("COMMIT")


_TABLES = frozenset({"meta", "state", "events", "outbox", "audit"})
# SQLite result codes that mean "try again later", not "this file is damaged".
_TRANSIENT_CODES = frozenset(
    {
        sqlite3.SQLITE_BUSY,
        sqlite3.SQLITE_LOCKED,
        sqlite3.SQLITE_NOMEM,
        sqlite3.SQLITE_IOERR,
        sqlite3.SQLITE_FULL,
        sqlite3.SQLITE_CANTOPEN,
        sqlite3.SQLITE_PROTOCOL,
        sqlite3.SQLITE_READONLY,
    }
)


def _transient(exc: sqlite3.Error) -> bool:
    code = getattr(exc, "sqlite_errorcode", None)
    return isinstance(code, int) and (code & 0xFF) in _TRANSIENT_CODES


def _short(exc: BaseException) -> str:
    text = str(exc)
    return text if len(text) <= 200 else text[:200] + "..."


def _lock(path: Path) -> int:
    # Key the lock on the resolved path, so a symlink to the store shares it.
    resolved = path.resolve()
    lock_path = resolved.with_name(resolved.name + ".lock")
    try:
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    except OSError as exc:
        raise StoreUnavailable(f"cannot open {lock_path}: {exc}") from exc
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        os.close(fd)
        raise StoreLocked(f"{path} is open in another process") from exc
    except OSError as exc:
        os.close(fd)
        raise StoreUnavailable(f"cannot lock {lock_path}: {exc}") from exc
    return fd


def _unlock(fd: int) -> None:
    fcntl.flock(fd, fcntl.LOCK_UN)
    os.close(fd)


def _build(path: Path, dev_mode: bool) -> None:
    """Write a complete new store next to `path`, then link it into place."""
    fd, temp_name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".init")
    os.close(fd)
    temp = Path(temp_name)
    try:
        try:
            connection = sqlite3.connect(temp, isolation_level=None)
            try:
                connection.execute("BEGIN IMMEDIATE")
                for statement in _SCHEMA:
                    connection.execute(statement)
                connection.executemany(
                    "INSERT INTO meta (key, value) VALUES (?, ?)",
                    [
                        ("schema_version", str(SCHEMA_VERSION)),
                        ("created_by", core_version()),
                        ("dev_mode", "1" if dev_mode else "0"),
                    ],
                )
                connection.execute(
                    "INSERT INTO state (id, seq, body) VALUES (1, 0, ?)",
                    (codec.dumps(empty_state()),),
                )
                connection.execute("COMMIT")
            finally:
                connection.close()
        except sqlite3.Error as exc:
            raise StoreUnavailable(f"could not create {path}: {exc}") from exc
        try:
            os.link(temp, path)
        except FileExistsError as exc:
            raise StoreError(f"{path} already exists") from exc
        except OSError as exc:
            raise StoreUnavailable(f"could not create {path}: {exc}") from exc
    finally:
        temp.unlink(missing_ok=True)


def _connect_existing(path: Path) -> sqlite3.Connection:
    """Open an existing store; refuse files that are not stores before changing them."""
    # mode=rw never creates a file; the WAL switch below happens only after
    # the file is known to be a LiveFactory store.
    connection = sqlite3.connect(
        f"{path.resolve().as_uri()}?mode=rw", uri=True, isolation_level=None
    )
    try:
        tables = {
            str(row[0])
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        if "meta" not in tables:
            raise StoreIncompatible(f"{path} is not a LiveFactory store")
        missing = _TABLES - tables
        if missing:
            raise StoreCorrupt(f"{path} is missing tables {sorted(missing)}")
        # isolation_level=None: no implicit transactions; every write is an
        # explicit BEGIN IMMEDIATE ... COMMIT (spec section 5).
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = FULL")
        connection.execute("PRAGMA foreign_keys = ON")
    except BaseException:
        connection.close()
        raise
    return connection


def _close_quietly(connection: sqlite3.Connection | None) -> None:
    if connection is not None:
        try:
            connection.close()
        except sqlite3.Error:
            pass


def _text(value: object) -> str:
    """Stored text, read as bytes so bad UTF-8 is a decode error we classify."""
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)


def _decode(value: object, what: str) -> Any:
    try:
        return codec.loads(_text(value))
    except (codec.CodecError, UnicodeDecodeError) as exc:
        raise StoreCorrupt(f"{what} does not decode: {_short(exc)}") from exc


def _load_checked(connection: sqlite3.Connection) -> tuple[FactoryState, int, bool]:
    """Read and vet the stored state (spec section 15.2: check before ready)."""
    meta = {
        _text(key): _text(value)
        for key, value in connection.execute(
            "SELECT CAST(key AS BLOB), CAST(value AS BLOB) FROM meta"
        ).fetchall()
    }
    version = meta.get("schema_version")
    if version != str(SCHEMA_VERSION):
        raise StoreIncompatible(f"schema version {version!r}; this code handles {SCHEMA_VERSION}")
    if connection.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
        raise StoreCorrupt("integrity check failed")
    if connection.execute("PRAGMA foreign_key_check").fetchall():
        raise StoreCorrupt("foreign key check failed")

    row = connection.execute("SELECT seq, CAST(body AS BLOB) FROM state WHERE id = 1").fetchone()
    if row is None:
        raise StoreCorrupt("no state row")
    seq = int(row[0])
    last = connection.execute("SELECT COALESCE(MAX(seq), 0) FROM events").fetchone()
    if last is None or int(last[0]) != seq:
        raise StoreCorrupt(f"state is at event {seq} but the log ends at {last}")
    state = _decode(row[1], "stored state")
    if not isinstance(state, FactoryState):
        raise StoreCorrupt("stored state has the wrong type")
    try:
        problems = state_violations(state)
    except Exception as exc:  # wrong types inside a state that decoded
        raise StoreCorrupt(f"stored state is malformed: {type(exc).__name__}: {_short(exc)}") from exc
    if problems:
        raise StoreCorrupt("stored state violates invariants: " + "; ".join(problems))

    # Messages still to deliver must be readable by this version too.
    for (body,) in connection.execute(
        "SELECT CAST(body AS BLOB) FROM outbox WHERE delivered = 0"
    ).fetchall():
        message = _decode(body, "undelivered outbox message")
        if not isinstance(message, _OUTBOX_TYPES):
            raise StoreCorrupt("undelivered outbox message has the wrong type")
    return state, seq, meta.get("dev_mode") == "1"
