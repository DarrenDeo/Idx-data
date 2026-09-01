#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project_dir="$(cd "${script_dir}/.." && pwd)"
backup_dir="${IDX_BACKUP_DIR:-${project_dir}/backups}"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"

mkdir -p "${backup_dir}"
cd "${project_dir}"

docker compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
  | gzip > "${backup_dir}/idx-${timestamp}.sql.gz"

echo "Backup written to ${backup_dir}/idx-${timestamp}.sql.gz"

