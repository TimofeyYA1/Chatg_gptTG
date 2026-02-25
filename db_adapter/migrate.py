from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from sqlalchemy import inspect, text

from db_adapter.database import engine


@dataclass(frozen=True)
class Migration:
    name: str
    run: Callable


def _ensure_migrations_table(conn) -> None:
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                id VARCHAR(255) PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
    )


def _is_applied(conn, migration_id: str) -> bool:
    row = conn.execute(
        text("SELECT 1 FROM schema_migrations WHERE id = :id LIMIT 1"),
        {"id": migration_id},
    ).first()
    return row is not None


def _mark_applied(conn, migration_id: str) -> None:
    conn.execute(
        text("INSERT INTO schema_migrations (id) VALUES (:id)"),
        {"id": migration_id},
    )


def _promo_tokens_multi_use_columns(conn) -> None:
    table_names = set(inspect(conn).get_table_names())
    if "promo_tokens" not in table_names:
        print("[migrations] promo_tokens table is missing, skip promo migration")
        return

    # Add only additive columns; existing data stays untouched.
    conn.execute(
        text(
            "ALTER TABLE promo_tokens "
            "ADD COLUMN IF NOT EXISTS max_uses INTEGER NOT NULL DEFAULT 1"
        )
    )
    conn.execute(
        text(
            "ALTER TABLE promo_tokens "
            "ADD COLUMN IF NOT EXISTS current_uses INTEGER NOT NULL DEFAULT 0"
        )
    )

    # Backfill counters from historical usages, preserving the maximum known value.
    if "promo_usages" in table_names:
        conn.execute(
            text(
                """
                UPDATE promo_tokens t
                SET current_uses = GREATEST(
                    COALESCE(t.current_uses, 0),
                    COALESCE(u.cnt, 0),
                    CASE WHEN t.is_used THEN 1 ELSE 0 END
                )
                FROM (
                    SELECT token_id, COUNT(*)::int AS cnt
                    FROM promo_usages
                    GROUP BY token_id
                ) u
                WHERE t.id = u.token_id
                """
            )
        )

    conn.execute(
        text(
            """
            UPDATE promo_tokens
            SET current_uses = 1
            WHERE is_used = TRUE
              AND current_uses < 1
            """
        )
    )
    conn.execute(text("ALTER TABLE promo_tokens ALTER COLUMN max_uses SET DEFAULT 1"))
    conn.execute(text("ALTER TABLE promo_tokens ALTER COLUMN current_uses SET DEFAULT 0"))


def _promo_tokens_credits_default_50(conn) -> None:
    table_names = set(inspect(conn).get_table_names())
    if "promo_tokens" not in table_names:
        print("[migrations] promo_tokens table is missing, skip credits default migration")
        return
    conn.execute(text("ALTER TABLE promo_tokens ALTER COLUMN credits SET DEFAULT 50"))


def _track_links_tables(conn) -> None:
    table_names = set(inspect(conn).get_table_names())
    if "users" not in table_names:
        print("[migrations] users table is missing, skip track links migration")
        return

    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS track_links (
                id SERIAL PRIMARY KEY,
                token VARCHAR(64) NOT NULL UNIQUE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_track_links_token ON track_links (token)"
        )
    )

    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS track_link_clicks (
                id SERIAL PRIMARY KEY,
                link_id INTEGER NOT NULL REFERENCES track_links(id) ON DELETE CASCADE,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                clicked_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_track_link_clicks_link_id ON track_link_clicks (link_id)"
        )
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_track_link_clicks_user_id ON track_link_clicks (user_id)"
        )
    )


MIGRATIONS: list[Migration] = [
    Migration("20260223_01_promo_tokens_multi_use_columns", _promo_tokens_multi_use_columns),
    Migration("20260223_02_promo_tokens_credits_default_50", _promo_tokens_credits_default_50),
    Migration("20260223_03_track_links_tables", _track_links_tables),
]


def run_migrations() -> None:
    with engine.begin() as conn:
        _ensure_migrations_table(conn)

    for migration in MIGRATIONS:
        with engine.begin() as conn:
            _ensure_migrations_table(conn)
            if _is_applied(conn, migration.name):
                print(f"[migrations] skip {migration.name} (already applied)")
                continue

            print(f"[migrations] applying {migration.name}")
            migration.run(conn)
            _mark_applied(conn, migration.name)
            print(f"[migrations] applied {migration.name}")


def main() -> None:
    run_migrations()
    print("[migrations] done")


if __name__ == "__main__":
    main()
