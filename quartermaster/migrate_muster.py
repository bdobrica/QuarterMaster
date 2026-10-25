"""One-time local data copy. No source writes, cookies, credentials or model requests."""

import argparse
import shutil
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

from quartermaster.config import Settings
from quartermaster.errors import DomainError
from quartermaster.muster_bundle import controlled, load_bundle, sha_file


def migrate_data(source: Path, destination: Path):
    # The operator-selected root may use a host directory alias (for example
    # ~/GitHub -> a Windows checkout). Links *inside* the data remain forbidden.
    source, destination = source.resolve(strict=True), destination.absolute()
    controlled(source)
    controlled(destination)
    if (
        destination.exists()
        or destination.is_relative_to(source)
        or source.is_relative_to(destination)
    ):
        raise DomainError("MUSTER_MIGRATION: Choose a new empty destination outside the source.")
    db_path = controlled(source / "muster.sqlite3")
    if not db_path.is_file():
        raise DomainError(
            "MUSTER_MIGRATION: Choose the old .muster data directory, not its code folder."
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
        staged = Path(temporary) / "muster"
        staged.mkdir()
        # sqlite3's transaction context does not close handles. Close explicitly
        # before moving the directory, including on Windows/WSL-mounted storage.
        with closing(sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True)) as original:
            with closing(sqlite3.connect(staged / "muster.sqlite3")) as copied:
                original.backup(copied)
                if copied.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise DomainError("MUSTER_MIGRATION: The source database needs recovery first.")
        for name in ("sources", "knowledge", "publications"):
            folder = source / name
            if not folder.is_dir():
                raise DomainError("MUSTER_MIGRATION: Restore the complete source data backup.")
            for file in folder.rglob("*"):
                controlled(file)
                if not file.is_file() and not file.is_dir():
                    raise DomainError("MUSTER_MIGRATION: Remove special files from source data.")
            shutil.copytree(folder, staged / name, symlinks=True)
            for file in folder.rglob("*"):
                if file.is_file() and sha_file(file) != sha_file(staged / file.relative_to(source)):
                    raise DomainError(
                        "MUSTER_MIGRATION: Source changed during the copy; stop Muster and retry."
                    )
        for manifest in (staged / "publications").glob("*/v*/manifest.json"):
            load_bundle(manifest.parent)
        # Browser profile/cookies, .env and connector credentials/configuration are
        # deliberately not migrated. Existing publications/reviews remain intact.
        staged.rename(destination)
    return destination


def main():
    parser = argparse.ArgumentParser(
        description="Copy existing Muster data into QuarterMaster. Stop both apps first."
    )
    parser.add_argument("source", type=Path)
    args = parser.parse_args()
    try:
        destination = migrate_data(args.source, Settings().muster_storage)
    except DomainError as exc:
        parser.exit(1, exc.message + " The original is unchanged.\n")
    except (OSError, sqlite3.Error, ValueError):
        parser.exit(
            1,
            "Muster data was not installed. Stop both apps; check the source and choose "
            "a new destination. The original is unchanged.\n",
        )
    print(f"Copied and checked Muster data into {destination}. Original data is unchanged.")


if __name__ == "__main__":
    main()
