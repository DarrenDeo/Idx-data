# Pop!_OS Always-On Deployment

This deployment uses the Pop!_OS PC as the server. There is no cloud-hosting
subscription: PostgreSQL data remains in a Docker volume on the PC. Electricity,
internet access, storage, and backups remain the owner's responsibility.

## Recommended server mode

The lightweight server profile runs:

- PostgreSQL for persistent storage;
- Redis for optional API caching;
- FastAPI for queries and Excel export;
- Nginx as the single HTTP entry point;
- a small weekday scheduler that runs a safe daily market update at 18:00 WIB.

Airflow, Prometheus, and Grafana remain available as optional profiles. Do not
run the lightweight scheduler and Airflow scheduler together, because both would
trigger the same daily market update.

## 1. Install Docker

Pop!_OS is Ubuntu-based. Docker documents that derivative distributions are not
officially tested, so match the Pop!_OS base Ubuntu release when following the
official Ubuntu repository instructions:

- https://docs.docker.com/engine/install/ubuntu/
- https://docs.docker.com/compose/install/linux/

System76 also documents `sudo apt install docker.io` as an alternative, although
the Ubuntu-maintained package can lag the current Docker release:

- https://support.system76.com/articles/rocm/

Verify the installation:

```bash
docker --version
docker compose version
sudo systemctl enable --now docker
```

If Docker was configured for non-root use, log out and back in after adding the
user to the `docker` group.

## 2. Copy and configure the project

Place the source at:

```text
~/idx-ohlcv-platform
```

Then configure it:

```bash
cd ~/idx-ohlcv-platform
cp .env.example .env
nano .env
```

At minimum, replace every `change-me` password. For private Tailscale access,
keep:

```dotenv
API_BIND_ADDRESS=127.0.0.1
API_HOST_PORT=80
```

For LAN-only access, `API_BIND_ADDRESS=0.0.0.0` makes port 80 reachable from
other computers. Do not expose PostgreSQL port 55432 or Redis directly to the
internet. Docker's own documentation warns that published container ports can
interact unexpectedly with host firewall rules.

## 3. Start the lightweight server

If this directory previously ran the full Compose stack, remove the old
containers first. Named PostgreSQL and Grafana volumes remain intact:

```bash
docker compose down --remove-orphans
docker compose --profile server up -d --build
docker compose exec api idx-platform init-db
docker compose exec api idx-platform sync-symbols
docker compose ps
```

The core containers use Docker's `unless-stopped` restart policy. Docker
restarts them after a process failure or daemon/PC restart, unless an operator
explicitly stopped them. This follows Docker's documented restart-policy model:

- https://docs.docker.com/engine/containers/start-containers-automatically/

## 4. Test API and Excel export

On the Pop!_OS PC:

```bash
curl http://127.0.0.1/health
```

Open the export form in a browser:

```text
http://127.0.0.1/export
```

Direct example:

```text
http://127.0.0.1/export/ohlcv.csv?symbols=BBCA,BBRI,TLKM&from=2026-08-24&to=2026-08-28
http://127.0.0.1/export/ohlcv.xlsx?symbols=BBCA,BBRI,TLKM&from=2026-08-24&to=2026-08-28
```

CSV is the lightest option and opens directly in Excel. The XLSX workbook
contains `Summary` and `OHLCV` sheets. Export is limited to 100,000 stored valid
candles per file; narrow the symbols or date range for larger data.

## 5. Private remote access with Tailscale

The safest simple option is to keep Nginx bound to `127.0.0.1` and expose it only
inside a private Tailscale network. Tailscale documents Linux installation and
Serve at:

- https://tailscale.com/docs/install/linux
- https://tailscale.com/docs/features/tailscale-serve

After installing and authenticating Tailscale:

```bash
sudo tailscale up
sudo tailscale serve --bg http://127.0.0.1:80
tailscale serve status
```

Open the reported HTTPS URL from another device signed into the same tailnet.
Do not use Tailscale Funnel or router port-forwarding unless public internet
exposure, authentication, rate limits, and TLS have been deliberately designed.

## 6. Daily updates

The `server` profile runs `app.scheduler` at 18:00 Asia/Jakarta every weekday.
Change the time in `.env` if needed:

```dotenv
SCHEDULER_HOUR=18
SCHEDULER_MINUTE=0
```

Check its logs:

```bash
docker compose logs --tail=100 scheduler
```

The scheduler starts after the latest market date stored globally and fetches
every missing calendar date through today. This safely catches up after downtime
without making a partially seeded database start a listing-date backfill for all
symbols. Use the explicit `backfill` command for older historical gaps.

## 7. Move the current database from Windows (optional)

If the Windows installation already contains the data you want to keep, create
a portable PostgreSQL dump from the project directory in PowerShell:

```powershell
docker compose exec postgres pg_dump -U idx -d idx -Fc -f /tmp/idx.dump
docker compose cp postgres:/tmp/idx.dump ./idx.dump
```

Copy `idx.dump` to `~/idx-ohlcv-platform` on Pop!_OS. Start PostgreSQL, then
restore into the target database:

```bash
cd ~/idx-ohlcv-platform
docker compose up -d postgres
docker compose cp ./idx.dump postgres:/tmp/idx.dump
docker compose exec postgres pg_restore -U idx -d idx --clean --if-exists /tmp/idx.dump
```

`--clean` replaces existing objects in the target `idx` database, so use this on
the new server before loading unrelated data. After restore, start the complete
server profile and verify `/health` and `/export`.

## 8. Backups

Create a backup manually:

```bash
cd ~/idx-ohlcv-platform
chmod +x scripts/backup-postgres.sh
./scripts/backup-postgres.sh
```

Backups are written under `backups/` by default. Copy them to another disk or
machine; a backup stored only on the server's system disk does not protect
against disk failure.

For a daily 02:00 backup, run `crontab -e` and add (replace `YOUR_USER`):

```cron
0 2 * * * /home/YOUR_USER/idx-ohlcv-platform/scripts/backup-postgres.sh >> /home/YOUR_USER/idx-ohlcv-platform/backups/backup.log 2>&1
```

## 9. Optional full operations stack

Use Airflow for scheduling and Prometheus/Grafana for monitoring instead of the
lightweight scheduler:

```bash
docker compose down --remove-orphans
docker compose --profile airflow --profile monitoring up -d --build
```

This mode consumes more RAM and disk. Do not enable the `server` profile at the
same time.

## 10. Updating the application

After copying a newer source revision:

```bash
cd ~/idx-ohlcv-platform
docker compose --profile server up -d --build
docker compose ps
curl http://127.0.0.1/health
```

The PostgreSQL named volume is not rebuilt with the application image.
