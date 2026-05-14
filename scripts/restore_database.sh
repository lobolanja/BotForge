#!/usr/bin/env bash
set -euo pipefail

backup_file=""
backup_dir="backups"
project_name=""
force="false"

usage() {
    cat <<'EOF'
Usage: scripts/restore_database.sh [--backup-file FILE] [--backup-dir DIR] [--project-name NAME] [--force]

Restores a compressed PostgreSQL dump into the running Docker Compose postgres
service. With no arguments, the script restores the newest *.dump file from
backups/.
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --backup-file)
            backup_file="${2:?Missing value for --backup-file}"
            shift 2
            ;;
        --backup-dir)
            backup_dir="${2:?Missing value for --backup-dir}"
            shift 2
            ;;
        --project-name)
            project_name="${2:?Missing value for --project-name}"
            shift 2
            ;;
        --force)
            force="true"
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown argument: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if [[ -z "$backup_file" ]]; then
    latest_backup=""
    for candidate in "$backup_dir"/*.dump; do
        [[ -e "$candidate" ]] || continue
        if [[ -z "$latest_backup" || "$candidate" -nt "$latest_backup" ]]; then
            latest_backup="$candidate"
        fi
    done
    backup_file="$latest_backup"
fi

if [[ -z "$backup_file" || ! -f "$backup_file" ]]; then
    echo "No database backup found. Run scripts/backup_database.sh first." >&2
    exit 1
fi

compose_args=(compose)
if [[ -n "$project_name" ]]; then
    compose_args+=(-p "$project_name")
fi

container_id="$(docker "${compose_args[@]}" ps -q postgres)"
if [[ -z "$container_id" ]]; then
    echo "PostgreSQL container is not running. Start it with 'docker compose up -d postgres'." >&2
    exit 1
fi

if [[ "$force" != "true" ]]; then
    echo "Restoring latest database backup: $backup_file"
else
    echo "Restoring database backup: $backup_file"
fi

docker cp "$backup_file" "${container_id}:/tmp/botforge-postgres-restore.dump"
docker "${compose_args[@]}" exec -T postgres sh -lc \
    'pg_restore --clean --if-exists --no-owner -U "$POSTGRES_USER" -d "$POSTGRES_DB" /tmp/botforge-postgres-restore.dump'
docker "${compose_args[@]}" exec -T postgres rm -f /tmp/botforge-postgres-restore.dump

echo "Restored database backup into the running PostgreSQL service."
