#!/usr/bin/env python3
"""Stage Letter Gate 0B — minimal SQLite persistence experiment.

Gate 0B-2 proved restart safety and atomicity. Gate 0B-3 extends the durable
projection with bootstrap-live provenance and an observation ordering watermark.
SQLite remains a Gate harness, not a production database decision.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from state_engine import (
    EngineConfig,
    EngineSnapshot,
    EngineState,
    LiveEvent,
    LiveEventCause,
    LiveEventType,
    LiveObservation,
    LiveSession,
    LiveSessionSnapshot,
    ProcessResult,
    SessionOrigin,
    StateEngine,
)


@dataclass(frozen=True)
class DurableSnapshot:
    account_id: str
    state: EngineState
    live_streak: int
    offline_streak: int
    sessions: tuple[LiveSession, ...]
    events: tuple[LiveEvent, ...]
    observation_count: int
    observation_watermark: datetime | None

    @property
    def open_session(self) -> LiveSession | None:
        open_sessions = [session for session in self.sessions if session.is_open]
        if len(open_sessions) > 1:
            raise AssertionError("durable invariant violated: multiple open sessions")
        return open_sessions[0] if open_sessions else None


class InjectedPersistenceFailure(RuntimeError):
    """Gate-only fault used to prove transaction rollback."""


class PersistentStateEngine:
    def __init__(
        self,
        db_path: str | Path,
        account_id: str,
        config: EngineConfig | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.account_id = account_id
        self.requested_config = config
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    @staticmethod
    def _ensure_column(
        connection: sqlite3.Connection,
        table: str,
        column: str,
        definition: str,
    ) -> None:
        columns = {
            row["name"]
            for row in connection.execute(f"PRAGMA table_info({table})")
        }
        if column not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")

    def _initialize(self) -> None:
        connection = self._connect()
        try:
            with connection:
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS engine_state (
                        account_id TEXT PRIMARY KEY,
                        state TEXT NOT NULL,
                        live_streak INTEGER NOT NULL CHECK (live_streak >= 0),
                        offline_streak INTEGER NOT NULL CHECK (offline_streak >= 0),
                        next_session_id INTEGER NOT NULL CHECK (next_session_id >= 1),
                        live_confirmations_required INTEGER NOT NULL CHECK (live_confirmations_required >= 1),
                        offline_confirmations_required INTEGER NOT NULL CHECK (offline_confirmations_required >= 1),
                        observation_watermark TEXT
                    );

                    CREATE TABLE IF NOT EXISTS observations (
                        account_id TEXT NOT NULL,
                        observation_id TEXT NOT NULL,
                        status TEXT NOT NULL,
                        observed_at TEXT NOT NULL,
                        source TEXT NOT NULL,
                        source_started_at TEXT,
                        PRIMARY KEY (account_id, observation_id)
                    );

                    CREATE TABLE IF NOT EXISTS sessions (
                        account_id TEXT NOT NULL,
                        session_id INTEGER NOT NULL,
                        opened_at TEXT NOT NULL,
                        closed_at TEXT,
                        origin TEXT NOT NULL DEFAULT 'TRANSITION',
                        source_started_at TEXT,
                        PRIMARY KEY (account_id, session_id)
                    );

                    CREATE UNIQUE INDEX IF NOT EXISTS one_open_session_per_account
                        ON sessions(account_id)
                        WHERE closed_at IS NULL;

                    CREATE TABLE IF NOT EXISTS events (
                        account_id TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        session_id INTEGER NOT NULL,
                        occurred_at TEXT NOT NULL,
                        cause TEXT NOT NULL DEFAULT 'TRANSITION',
                        PRIMARY KEY (account_id, event_type, session_id),
                        FOREIGN KEY (account_id, session_id)
                            REFERENCES sessions(account_id, session_id)
                    );
                    """
                )

                # Forward-compatible Gate migration for local SQLite files
                # created by Gate 0B-2 before bootstrap/watermark fields existed.
                self._ensure_column(
                    connection,
                    "engine_state",
                    "observation_watermark",
                    "observation_watermark TEXT",
                )
                self._ensure_column(
                    connection,
                    "observations",
                    "source_started_at",
                    "source_started_at TEXT",
                )
                self._ensure_column(
                    connection,
                    "sessions",
                    "origin",
                    "origin TEXT NOT NULL DEFAULT 'TRANSITION'",
                )
                self._ensure_column(
                    connection,
                    "sessions",
                    "source_started_at",
                    "source_started_at TEXT",
                )
                self._ensure_column(
                    connection,
                    "events",
                    "cause",
                    "cause TEXT NOT NULL DEFAULT 'TRANSITION'",
                )

                row = connection.execute(
                    "SELECT * FROM engine_state WHERE account_id = ?",
                    (self.account_id,),
                ).fetchone()

                if row is None:
                    config = self.requested_config or EngineConfig()
                    connection.execute(
                        """
                        INSERT INTO engine_state (
                            account_id, state, live_streak, offline_streak,
                            next_session_id, live_confirmations_required,
                            offline_confirmations_required, observation_watermark
                        ) VALUES (?, ?, 0, 0, 1, ?, ?, NULL)
                        """,
                        (
                            self.account_id,
                            EngineState.UNKNOWN.value,
                            config.live_confirmations_required,
                            config.offline_confirmations_required,
                        ),
                    )
                elif self.requested_config is not None:
                    persisted = EngineConfig(
                        live_confirmations_required=row["live_confirmations_required"],
                        offline_confirmations_required=row["offline_confirmations_required"],
                    )
                    if persisted != self.requested_config:
                        raise ValueError("persisted EngineConfig differs from requested config")
        finally:
            connection.close()

    def _load_engine(self, connection: sqlite3.Connection) -> StateEngine:
        row = connection.execute(
            "SELECT * FROM engine_state WHERE account_id = ?",
            (self.account_id,),
        ).fetchone()
        if row is None:
            raise AssertionError("durable invariant violated: missing engine_state")

        config = EngineConfig(
            live_confirmations_required=row["live_confirmations_required"],
            offline_confirmations_required=row["offline_confirmations_required"],
        )
        sessions = tuple(
            LiveSessionSnapshot(
                session_id=session_row["session_id"],
                opened_at=datetime.fromisoformat(session_row["opened_at"]),
                closed_at=(
                    datetime.fromisoformat(session_row["closed_at"])
                    if session_row["closed_at"] is not None
                    else None
                ),
                origin=SessionOrigin(session_row["origin"]),
                source_started_at=(
                    datetime.fromisoformat(session_row["source_started_at"])
                    if session_row["source_started_at"] is not None
                    else None
                ),
            )
            for session_row in connection.execute(
                """
                SELECT session_id, opened_at, closed_at, origin, source_started_at
                FROM sessions
                WHERE account_id = ?
                ORDER BY session_id
                """,
                (self.account_id,),
            )
        )
        events = tuple(
            LiveEvent(
                event_type=LiveEventType(event_row["event_type"]),
                session_id=event_row["session_id"],
                occurred_at=datetime.fromisoformat(event_row["occurred_at"]),
                cause=LiveEventCause(event_row["cause"]),
            )
            for event_row in connection.execute(
                """
                SELECT event_type, session_id, occurred_at, cause
                FROM events
                WHERE account_id = ?
                ORDER BY occurred_at, session_id, event_type
                """,
                (self.account_id,),
            )
        )
        seen_ids = frozenset(
            observation_row["observation_id"]
            for observation_row in connection.execute(
                "SELECT observation_id FROM observations WHERE account_id = ?",
                (self.account_id,),
            )
        )
        snapshot = EngineSnapshot(
            state=EngineState(row["state"]),
            live_streak=row["live_streak"],
            offline_streak=row["offline_streak"],
            sessions=sessions,
            events=events,
            seen_observation_ids=seen_ids,
            next_session_id=row["next_session_id"],
            observation_watermark=(
                datetime.fromisoformat(row["observation_watermark"])
                if row["observation_watermark"] is not None
                else None
            ),
        )
        return StateEngine.from_snapshot(snapshot, config)

    def _write_engine(
        self,
        connection: sqlite3.Connection,
        engine: StateEngine,
        *,
        inject_failure_at: str | None = None,
    ) -> None:
        snapshot = engine.snapshot()
        connection.execute(
            """
            UPDATE engine_state
            SET state = ?, live_streak = ?, offline_streak = ?, next_session_id = ?,
                observation_watermark = ?
            WHERE account_id = ?
            """,
            (
                snapshot.state.value,
                snapshot.live_streak,
                snapshot.offline_streak,
                snapshot.next_session_id,
                (
                    snapshot.observation_watermark.isoformat()
                    if snapshot.observation_watermark is not None
                    else None
                ),
                self.account_id,
            ),
        )

        # Events depend on sessions through a foreign key, so the durable
        # projection is rebuilt in dependency-safe order inside the same tx.
        connection.execute("DELETE FROM events WHERE account_id = ?", (self.account_id,))
        connection.execute("DELETE FROM sessions WHERE account_id = ?", (self.account_id,))
        connection.executemany(
            """
            INSERT INTO sessions (
                account_id, session_id, opened_at, closed_at, origin, source_started_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    self.account_id,
                    session.session_id,
                    session.opened_at.isoformat(),
                    session.closed_at.isoformat() if session.closed_at else None,
                    session.origin.value,
                    (
                        session.source_started_at.isoformat()
                        if session.source_started_at is not None
                        else None
                    ),
                )
                for session in snapshot.sessions
            ],
        )

        if inject_failure_at == "after_sessions_write":
            raise InjectedPersistenceFailure("after_sessions_write")

        connection.executemany(
            """
            INSERT INTO events (account_id, event_type, session_id, occurred_at, cause)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (
                    self.account_id,
                    event.event_type.value,
                    event.session_id,
                    event.occurred_at.isoformat(),
                    event.cause.value,
                )
                for event in snapshot.events
            ],
        )

    def process(
        self,
        observation: LiveObservation,
        *,
        inject_failure_at: str | None = None,
    ) -> ProcessResult:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            engine = self._load_engine(connection)
            result = engine.process(observation)

            if result.duplicate:
                connection.rollback()
                return result

            # Accepted and stale-new observations are both durable ledger facts.
            # A stale observation changes only durable idempotency, never the
            # canonical state/watermark projection.
            connection.execute(
                """
                INSERT INTO observations (
                    account_id, observation_id, status, observed_at, source,
                    source_started_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    self.account_id,
                    observation.observation_id,
                    observation.status.value,
                    observation.observed_at.isoformat(),
                    observation.source,
                    (
                        observation.source_started_at.isoformat()
                        if observation.source_started_at is not None
                        else None
                    ),
                ),
            )

            if inject_failure_at == "after_observation_insert":
                raise InjectedPersistenceFailure("after_observation_insert")

            self._write_engine(
                connection,
                engine,
                inject_failure_at=inject_failure_at,
            )

            if inject_failure_at == "after_state_write":
                raise InjectedPersistenceFailure("after_state_write")

            connection.commit()
            return result
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def snapshot(self) -> DurableSnapshot:
        connection = self._connect()
        try:
            engine = self._load_engine(connection)
            observation_count = connection.execute(
                "SELECT COUNT(*) FROM observations WHERE account_id = ?",
                (self.account_id,),
            ).fetchone()[0]
            return DurableSnapshot(
                account_id=self.account_id,
                state=engine.state,
                live_streak=engine.live_streak,
                offline_streak=engine.offline_streak,
                sessions=tuple(engine.sessions),
                events=tuple(engine.events),
                observation_count=observation_count,
                observation_watermark=engine.observation_watermark,
            )
        finally:
            connection.close()
