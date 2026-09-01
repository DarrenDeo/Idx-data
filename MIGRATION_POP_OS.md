# Migrasi IDX Data ke Pop!_OS

Nama proyek di server: `idx-data`

## A. Ekspor database dari Windows

Jalankan dari direktori proyek Windows:

```powershell
docker compose exec postgres pg_dump -U idx -d idx -Fc -f /tmp/idx-data.dump
docker compose cp postgres:/tmp/idx-data.dump ./idx-data.dump
```

Cara ini menjaga file dump tetap biner dan menghindari perubahan byte oleh
redirection PowerShell.

## B. Kirim source dan database

Ganti `POP_USER` dan `POP_HOST`:

```powershell
scp .\outputs\idx-data.zip POP_USER@POP_HOST:~/
scp .\idx-data.dump POP_USER@POP_HOST:~/
```

Alamat `POP_HOST` dapat berupa IP LAN, nama host, atau IP Tailscale.

## C. Siapkan proyek di Pop!_OS

```bash
cd ~
unzip -o idx-data.zip
cd ~/idx-data
cp .env.example .env
nano .env
```

Ganti seluruh nilai `change-me` sebelum pertama kali menjalankan PostgreSQL.
Pertahankan:

```dotenv
API_BIND_ADDRESS=127.0.0.1
API_HOST_PORT=80
```

## D. Restore database

```bash
cd ~/idx-data
docker compose up -d postgres
docker compose cp ~/idx-data.dump postgres:/tmp/idx-data.dump
docker compose exec postgres pg_restore -U idx -d idx --clean --if-exists --no-owner /tmp/idx-data.dump
```

Pesan bahwa objek lama tidak ditemukan dapat terjadi pada database baru dan
tidak selalu berarti restore gagal. Periksa tabel setelah restore:

```bash
docker compose exec postgres psql -U idx -d idx -c "SELECT COUNT(*) AS candles, COUNT(DISTINCT symbol) AS symbols, MIN(trade_date), MAX(trade_date) FROM ohlcv_daily;"
```

## E. Jalankan server

```bash
docker compose --profile server up -d --build
docker compose ps
curl http://127.0.0.1/health
```

Halaman ekspor:

```text
http://127.0.0.1/export
```

Periksa scheduler:

```bash
docker compose logs --tail=100 scheduler
```

## F. Akses privat melalui Tailscale

```bash
sudo tailscale up
sudo tailscale serve --bg http://127.0.0.1:80
tailscale serve status
```

Gunakan alamat HTTPS yang ditampilkan dari perangkat dalam tailnet yang sama.
Jangan membuka port aplikasi ke internet publik karena API belum memiliki login.

## G. Verifikasi setelah migrasi

```bash
curl http://127.0.0.1/health
curl -OJ "http://127.0.0.1/export/ohlcv.csv?symbols=BBCA,BBRI,TLKM&from=2026-08-24&to=2026-08-28"
docker compose --profile test run --build --rm tests
```

Database persisten berada dalam Docker volume. Container utama memakai
`unless-stopped`, sehingga akan kembali hidup setelah Docker atau PC restart.
