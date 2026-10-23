import sqlite3

from pydantic import ValidationError

from quartermaster.config import Settings, initialize_storage
from quartermaster.db import SCHEMA_VERSION, SchemaError, migrate


def main() -> None:
    try:
        settings = Settings()
        initialize_storage(settings)
        migrate(settings.database_path)
    except SchemaError as exc:
        raise SystemExit(str(exc)) from None
    except (OSError, sqlite3.Error, ValidationError):
        raise SystemExit(
            "STORAGE_INIT: Check QM_DATA_DIR, configuration and disk permissions."
        ) from None
    print(f"SQLite schema v{SCHEMA_VERSION} ready.")


if __name__ == "__main__":
    main()
