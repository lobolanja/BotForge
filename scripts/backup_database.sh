#!/usr/bin/env bash
set -euo pipefail

backup_dir="backups"
project_name=""

usage() {
    cat <<'EOF'
Usage: scripts/backup_database.sh [--backup-dir DIR] [--project-name NAME]

Creates a compressed PostgreSQL dump from the running Docker Compose postgres
service. The default output directory is backups/.
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --backup-dir)
            backup_dir="${2:?Missing value for --backup-dir}"
            shift 2
            ;;
        --project-name)
            project_name="${2:?Missing value for --project-name}"
            shift 2
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

compose_args=(compose)
if [[ -n "$project_name" ]]; then
    compose_args+=(-p "$project_name")
fi

mkdir -p "$backup_dir"
backup_path="$backup_dir/botforge-postgres-$(date +%Y%m%d-%H%M%S).dump"

container_id="$(docker "${compose_args[@]}" ps -q postgres)"
if [[ -z "$container_id" ]]; then
    echo "PostgreSQL container is not running. Start it with 'docker compose up -d postgres'." >&2
    exit 1
fi

docker "${compose_args[@]}" exec -T postgres sh -lc \
    'pg_dump -Fc -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f /tmp/botforge-postgres.dump'
docker cp "${container_id}:/tmp/botforge-postgres.dump" "$backup_path"
docker "${compose_args[@]}" exec -T postgres rm -f /tmp/botforge-postgres.dump

echo "Created database backup: $backup_path"
