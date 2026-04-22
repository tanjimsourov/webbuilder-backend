# Backup and Restore

## Database (PostgreSQL)

Scripts:

- `scripts/backup_database.py`
- `scripts/restore_database.py`

### Backup

```bash
python scripts/backup_database.py --output ./var/backups
```

### Restore

```bash
python scripts/restore_database.py --input ./var/backups/<file>.sql.gz
```

## File/Object Storage

### Local media volume

- Archive `./media/` and `./var/` directories.

### MinIO / S3-compatible

- Use bucket-level versioning and lifecycle policies.
- Run periodic object inventory + replication snapshots.

## Operational policy

- Minimum daily full DB backup.
- Keep 7 daily, 4 weekly, 6 monthly snapshots.
- Test restore in staging at least monthly.