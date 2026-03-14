#!/usr/bin/env python
"""
Database Restore Script

Restores PostgreSQL database from a backup file.
Supports both plain SQL and gzip-compressed backups.

Usage:
    python scripts/restore_database.py backup_file.sql
    python scripts/restore_database.py backup_file.sql.gz
    python scripts/restore_database.py backup_file.sql --confirm

Environment Variables:
    DJANGO_DB_NAME - Database name (default: smc_web_builder)
    DJANGO_DB_USER - Database user (default: smc_user)
    DJANGO_DB_HOST - Database host (default: localhost)
    DJANGO_DB_PORT - Database port (default: 5432)
    PGPASSWORD - Database password (set this for non-interactive use)

WARNING: This will DROP and recreate the database. All existing data will be lost.
"""

import argparse
import gzip
import os
import subprocess
import sys
from pathlib import Path


def get_db_config():
    """Get database configuration from environment."""
    return {
        "name": os.environ.get("DJANGO_DB_NAME", "smc_web_builder"),
        "user": os.environ.get("DJANGO_DB_USER", "smc_user"),
        "host": os.environ.get("DJANGO_DB_HOST", "localhost"),
        "port": os.environ.get("DJANGO_DB_PORT", "5432"),
    }


def restore_backup(backup_path: Path, confirm: bool = False) -> bool:
    """Restore database from backup file."""
    config = get_db_config()
    
    if not backup_path.exists():
        print(f"✗ Backup file not found: {backup_path}", file=sys.stderr)
        return False
    
    print(f"Restore target: {config['name']}@{config['host']}:{config['port']}")
    print(f"Backup file: {backup_path}")
    print(f"File size: {backup_path.stat().st_size / (1024 * 1024):.2f} MB")
    print()
    print("WARNING: This will DROP and recreate the database.")
    print("         All existing data will be PERMANENTLY LOST.")
    print()
    
    if not confirm:
        response = input("Type 'yes' to confirm restore: ")
        if response.lower() != "yes":
            print("Restore cancelled.")
            return False
    
    # Determine if compressed
    is_compressed = backup_path.suffix == ".gz"
    
    # Build psql command
    psql_cmd = [
        "psql",
        "-h", config["host"],
        "-p", config["port"],
        "-U", config["user"],
        "-d", config["name"],
        "--no-password",
        "-v", "ON_ERROR_STOP=1",
    ]
    
    print("Restoring database...")
    
    try:
        if is_compressed:
            with gzip.open(backup_path, "rt", encoding="utf-8") as f:
                sql_content = f.read()
            result = subprocess.run(
                psql_cmd,
                input=sql_content,
                capture_output=True,
                text=True,
            )
        else:
            with open(backup_path, "r", encoding="utf-8") as f:
                result = subprocess.run(
                    psql_cmd,
                    stdin=f,
                    capture_output=True,
                    text=True,
                )
        
        if result.returncode != 0:
            print(f"✗ Restore failed: {result.stderr}", file=sys.stderr)
            return False
        
        print("✓ Database restored successfully")
        return True
        
    except FileNotFoundError:
        print("✗ psql not found. Ensure PostgreSQL client tools are installed.", file=sys.stderr)
        return False
    except Exception as e:
        print(f"✗ Restore failed: {e}", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(description="Restore database from backup")
    parser.add_argument(
        "backup_file",
        type=Path,
        help="Path to backup file (.sql or .sql.gz)",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Skip confirmation prompt (use with caution)",
    )
    
    args = parser.parse_args()
    
    # Check for PGPASSWORD
    if not os.environ.get("PGPASSWORD"):
        print("Warning: PGPASSWORD not set. psql may prompt for password.", file=sys.stderr)
    
    success = restore_backup(args.backup_file, args.confirm)
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
