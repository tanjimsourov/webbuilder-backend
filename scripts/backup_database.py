#!/usr/bin/env python
"""
Database Backup Script

Creates timestamped PostgreSQL database backups with optional compression.
Designed for production use with cron or manual execution.

Usage:
    python scripts/backup_database.py
    python scripts/backup_database.py --output-dir /backups
    python scripts/backup_database.py --compress
    python scripts/backup_database.py --keep 7  # Keep last 7 backups

Environment Variables:
    DJANGO_DB_NAME - Database name (default: smc_web_builder)
    DJANGO_DB_USER - Database user (default: smc_user)
    DJANGO_DB_HOST - Database host (default: localhost)
    DJANGO_DB_PORT - Database port (default: 5432)
    PGPASSWORD - Database password (set this for non-interactive use)
"""

import argparse
import gzip
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path


def get_db_config():
    """Get database configuration from environment."""
    return {
        "name": os.environ.get("DJANGO_DB_NAME", "smc_web_builder"),
        "user": os.environ.get("DJANGO_DB_USER", "smc_user"),
        "host": os.environ.get("DJANGO_DB_HOST", "localhost"),
        "port": os.environ.get("DJANGO_DB_PORT", "5432"),
    }


def create_backup(output_dir: Path, compress: bool = False) -> Path:
    """Create a database backup."""
    config = get_db_config()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"backup_{config['name']}_{timestamp}.sql"
    
    if compress:
        filename += ".gz"
    
    output_path = output_dir / filename
    
    # Build pg_dump command
    cmd = [
        "pg_dump",
        "-h", config["host"],
        "-p", config["port"],
        "-U", config["user"],
        "-d", config["name"],
        "--no-password",
        "-F", "p",  # Plain text format
    ]
    
    print(f"Creating backup: {output_path}")
    print(f"Database: {config['name']}@{config['host']}:{config['port']}")
    
    try:
        if compress:
            # Pipe through gzip
            with gzip.open(output_path, "wt", encoding="utf-8") as f:
                result = subprocess.run(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    check=True,
                )
                f.write(result.stdout)
        else:
            # Direct output to file
            with open(output_path, "w", encoding="utf-8") as f:
                subprocess.run(
                    cmd,
                    stdout=f,
                    stderr=subprocess.PIPE,
                    check=True,
                )
        
        size_mb = output_path.stat().st_size / (1024 * 1024)
        print(f"✓ Backup created: {output_path} ({size_mb:.2f} MB)")
        return output_path
        
    except subprocess.CalledProcessError as e:
        print(f"✗ Backup failed: {e.stderr}", file=sys.stderr)
        if output_path.exists():
            output_path.unlink()
        sys.exit(1)
    except FileNotFoundError:
        print("✗ pg_dump not found. Ensure PostgreSQL client tools are installed.", file=sys.stderr)
        sys.exit(1)


def cleanup_old_backups(output_dir: Path, keep: int):
    """Remove old backups, keeping only the most recent ones."""
    backups = sorted(
        [f for f in output_dir.glob("backup_*.sql*") if f.is_file()],
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )
    
    to_delete = backups[keep:]
    for backup in to_delete:
        print(f"Removing old backup: {backup.name}")
        backup.unlink()
    
    if to_delete:
        print(f"✓ Removed {len(to_delete)} old backup(s)")


def main():
    parser = argparse.ArgumentParser(description="Create database backup")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("backups"),
        help="Directory to store backups (default: ./backups)",
    )
    parser.add_argument(
        "--compress",
        action="store_true",
        help="Compress backup with gzip",
    )
    parser.add_argument(
        "--keep",
        type=int,
        default=0,
        help="Number of backups to keep (0 = keep all)",
    )
    
    args = parser.parse_args()
    
    # Ensure output directory exists
    args.output_dir.mkdir(parents=True, exist_ok=True)
    
    # Check for PGPASSWORD
    if not os.environ.get("PGPASSWORD"):
        print("Warning: PGPASSWORD not set. pg_dump may prompt for password.", file=sys.stderr)
    
    # Create backup
    backup_path = create_backup(args.output_dir, args.compress)
    
    # Cleanup old backups if requested
    if args.keep > 0:
        cleanup_old_backups(args.output_dir, args.keep)
    
    print(f"\n✓ Backup complete: {backup_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
