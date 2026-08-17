#!/usr/bin/env python3
"""Stage Letter Gate 0B-2 — minimal SQLite persistence experiment.

This module deliberately stays below the production persistence layer. It uses
Python's standard-library sqlite3 module to prove restart safety, durable
idempotency, account isolation, and atomic persistence for the Gate 0B state
engine.

One PersistentStateEngine instance represents one PlatformAccount. Every
observation is processed in one SQLite transaction:

    load durable engine -> process observation -> persist observation/state/
    sessions/events -> COMMIT

If any write fails, the transaction rolls back and the next process loads the
last committed state. UNKNOWN semantics remain owned by state_engine.py.
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
    LiveEventType,
    LiveObservation,
    LiveSession,
    LiveSessionSnapshot,
    ProcessResult,
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

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS engine_state (
                    account_id TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    live_streak INTEGER NOT NULL CHECK (live_streak >= 0),
                    offline_streak INTEGER NOT NULL CHECK (offline_streak >= 0),
                    next_session_id INTEGER NOT NULL CHECK (next_session_id >= 1),
                    live_confirmations_required INTEGER NOT NULL CHECK (live_confirmations_required >= 1),
                    offline_confirmations_required INTEGER NOT NULL CHECK (offline_confirmations_required >= 1)
                );

                CREATE TABLE IF NOT EXISTS observations (
                    account_id TEXT NOT NULL,
                    observation_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    source TEXT NOT NULL,
                    PRIMARY KEY (account_id, observation_id)
                );

                CREATE TABLE IF NOT EXISTS sessions (
                    account_id TEXT NOT NULL,
                    session_id INTEGER NOT NULL,
                    opened_at TEXT NOT NULL,
                    closed_at TEXT,
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
                    PRIMARY KEY (account_id, event_type, session_id),
                    FOREIGN KEY (account_id, session_id)
                        REFERENCES sessions(account_id, session_id)
                );
                """
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
                        offline_confirmations_required
                    ) VALUES (?, ?, 0, 0, 1, ?, ?)
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
            )
            for session_row in connection.execute(
                """
                SELECT session_id, opened_at, closed_at
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
            )
            for event_row in connection.execute(
                """
                SELECT event_type, session_id, occurred_at
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
            SET state = ?, live_streak = ?, offline_streak = ?, next_session_id = ?
            WHERE account_id = ?
            """,
            (
                snapshot.state.value,
                snapshot.live_streak,
                snapshot.offline_streak,
                snapshot.next_session_id,
                self.account_id,
            ),
        )

        # Events depend on sessions through a foreign key, so the durable
        # projection is rebuilt in dependency-safe order inside the same tx.
        connection.execute("DELETE FROM events WHERE account_id = ?", (self.account_id,))
        connection.execute("DELETE FROM sessions WHERE account_id = ?", (self.account_id,))
        connection.executemany(
            """
            INSERT INTO sessions (account_id, session_id, opened_at, closed_at)
            VALUES (?, ?, ?, ?)
            """,
            [
                (
                    self.account_id,
                    session.session_id,
                    session.opened_at.isoformat(),
                    session.closed_at.isoformat() if session.closed_at else None,
                )
                for session in snapshot.sessions
            ],
        )

        if inject_failure_at == "after_sessions_write":
            raise InjectedPersistenceFailure("after_sessions_write")

        connection.executemany(
            """
            INSERT INTO events (account_id, event_type, session_id, occurred_at)
            VALUES (?, ?, ?, ?)
            """,
            [
                (
                    self.account_id,
                    event.event_type.value,
                    event.session_id,
                    event.occurred_at.isoformat(),
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

            connection.execute(
                """
                INSERT INTO observations (
                    account_id, observation_id, status, observed_at, source
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    self.account_id,
                    observation.observation_id,
                    observation.status.value,
                    observation.observed_at.isoformat(),
                    observation.source,
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
        with self._connect() as connection:
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
            )
