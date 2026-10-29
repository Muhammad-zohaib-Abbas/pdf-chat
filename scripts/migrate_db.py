"""Apply pending SQL migrations, remembering which ones already ran.

Usage (from the project root):
    python -m scripts.migrate_db
"""

import hashlib
from pathlib import Path

from app.database import get_connection

MIGRATION_DIR = Path(__file__).resolve().parents[1] / "migrations"
LOCK_ID = 727274  # arbitrary number: stops two migrators running at once


def migrate() -> None:
    migration_files = sorted(MIGRATION_DIR.glob("*.sql"))
    if not migration_files:
        print("No database migrations found.")
        return

    with get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                filename TEXT PRIMARY KEY,
                checksum CHAR(64) NOT NULL,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        connection.commit()
        connection.execute("SELECT pg_advisory_lock(%s)", (LOCK_ID,))

        try:
            applied = dict(
                connection.execute(
                    "SELECT filename, checksum FROM schema_migrations"
                ).fetchall()
            )
            connection.commit()

            for migration_file in migration_files:
                sql = migration_file.read_text(encoding="utf-8")
                checksum = hashlib.sha256(sql.encode("utf-8")).hexdigest()

                if migration_file.name in applied:
                    if applied[migration_file.name] != checksum:
                        print(
                            f"WARNING: {migration_file.name} changed after it "
                            "was applied. Add a new migration instead."
                        )
                    continue

                print(f"Applying {migration_file.name}...")
                try:
                    # Each file is all-or-nothing.
                    connection.execute(sql)
                    connection.execute(
                        "INSERT INTO schema_migrations (filename, checksum) "
                        "VALUES (%s, %s)",
                        (migration_file.name, checksum),
                    )
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
        finally:
            connection.execute("SELECT pg_advisory_unlock(%s)", (LOCK_ID,))
            connection.commit()

    print("Database migrations completed successfully.")


if __name__ == "__main__":
    migrate()
