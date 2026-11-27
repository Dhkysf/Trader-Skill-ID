# Trader Skill ID

English: [README.en.md](README.en.md)

Asisten analisis day-trading di Google Antigravity untuk trader Indonesia: saham Indonesia (IDX/BEI) dan spot forex 24/5.

Gratis, lisensi MIT, tanpa daftar akun, tanpa API key. Semua skrip memakai Python standar (3.8+) yang membaca data publik: grafik Yahoo Finance dan feed RSS keuangan Indonesia.

Satu skill memindai ribuan grafik untuk mencari setup. Skill lain memantau berita terbaru. Ada yang mengawasi candle demi candle untuk momen masuk, ada yang memasang stop dan target sebelum Anda masuk, dan Time Machine memutar ulang sisa sesi 10.000 kali dari data 60 hari terakhir sebelum Anda mempertaruhkan uang.

Tidak ada order yang berjalan tanpa persetujuan Anda. Semua order selalu manual, dengan paper trading sebagai bawaan.

## Istilah singkat

- **ORB (Opening-Range Breakout)**: penembusan harga di atas atau di bawah rentang harga pembukaan (bawaan 15 menit pertama).
- **Stop (stop-loss)**: batas harga keluar otomatis jika skenario gagal, untuk membatasi rugi.
- **R**: satuan risiko awal per transaksi (1R = jarak dari harga masuk ke stop; 2R = dua kali jarak tersebut).
- **ARA/ARB**: Auto Rejection Atas / Bawah, batas kenaikan dan penurunan harga harian saham di IDX.
- **Pip**: satuan gerak harga terkecil di pasangan forex (0,0001 untuk EURUSD; 0,01 untuk USDJPY; 1 untuk USDIDR).
- **Lot**: satuan ukuran transaksi (100 lembar saham di IDX; 100.000 unit mata uang dasar di forex, minimum 0,01 lot).

## Daftar skill

| Perintah | Tugas | Pasar | Fungsi |
| --- | --- | --- | --- |
| `/trader-scanner` | Pemindai Grafik | IDX, Forex | Mencari setup harian dan breakout rentang pembukaan (ORB). |
| `/trader-news` | Pemantau Berita | IDX (RSS + harga), Forex (harga) | Memantau berita RSS Indonesia dan pergerakan harga harian. |
| `/trader-entry` | Penentu Masuk | IDX, Forex | Mengawasi candle demi candle dan memberi tanda saat harga tutup menembus level. |
| `/trader-exit` | Perencana Keluar | IDX, Forex | Menentukan stop dan target sebelum masuk, termasuk cek tick dan ARA/ARB. |
| `/trader-timemachine` | Time Machine | IDX, Forex | Simulasi 10.000 sesi + riwayat aturan yang sama pada 60 hari terakhir. |
| `/trader-budget` | Pengatur Modal | IDX, Forex | Menghitung ukuran lot sesuai batas rugi maksimal per transaksi. |
| `/trader-risk` | Pemeriksa Risiko | IDX, Forex | Mengecek setiap order terhadap aturan Anda: PASS atau BLOCK dengan alasan. |
| `/trader-broker` | Tiket Manual | IDX, Forex | Menampilkan tiket order manual, mencatat persetujuan "yes" dan hasil fill. |
| `/trader-alerts` | Pengingat Harga | IDX, Forex | Berbunyi saat harga, stop, target, bel buka, atau waktu tutup tercapai. |

Modul bersama: `/trader-core` - aturan pasar, jam bursa, hari libur, dan pembulatan tick dari `markets/*.json`.

## Instalasi (Google Antigravity)

**(a) Disarankan: folder trading khusus (Antigravity IDE)**

Setiap skill menulis file kerja (`watchlist.json`, `plan.json`, `orders.json`, `state/`) ke dalam folder `trader\` di direktori kerja Anda. Memakai folder khusus menjaga file trading terpisah dari repositori kode.

Di PowerShell, salin skill ke `.agents\skills\` di folder trading Anda:

```powershell
New-Item -ItemType Directory -Force -Path "E:\Projects\Trading-Lab\.agents\skills"
Copy-Item -Recurse -Force ".\skills\trader-*" "E:\Projects\Trading-Lab\.agents\skills\"
```

Buka folder tersebut di Google Antigravity, mulai chat baru, lalu jalankan `/trader-news BBCA`.

**(b) Antigravity CLI (`agy`)**

```powershell
agy plugin install https://github.com/Dhkysf/Trader-Skill-ID
```

Membutuhkan Python 3.8 atau lebih baru. Tidak perlu `pip install`.

Untuk konfigurasi awal, salin contoh konfigurasi ke `trader\config.json`:
- IDX: `skills\trader-budget\config.example.json`
- Forex: `skills\trader-budget\config.fx.example.json`

## Cara kerja dan perintah

Semua skill saling berbagi file di folder `trader\`:

```text
scanner -> news -> entry -> exit -> timemachine -> budget -> risk -> broker   (satu transaksi)
alerts: stop, target, tutup sebelum pasar tutup                                (saat posisi terbuka)
news                                                                           (terjadwal)
```

Perintah Python langsung (Windows PowerShell; gunakan `python3` dan `/` di macOS/Linux):

```powershell
python skills\trader-scanner\scan.py universe --from data\daftar-saham.csv
python skills\trader-scanner\scan.py daily
python skills\trader-scanner\scan.py orb --at 10:15
python skills\trader-scanner\scan.py orb --session london
python skills\trader-news\news.py --tickers BBCA --hours 12
python skills\trader-entry\entry.py check BBCA --setup orb
python skills\trader-entry\entry.py watch BBCA --every 30
python skills\trader-exit\exit.py plan --stop or-mid --target 1R --write
python skills\trader-timemachine\timemachine.py run --write
python skills\trader-budget\size.py --write
python skills\trader-risk\check.py
python skills\trader-broker\ticket.py show
python skills\trader-alerts\alerts.py add --from-plan
python skills\trader-alerts\alerts.py check
```

Menjalankan tes offline:

```powershell
.\check.bat nopause
python -m unittest discover -s tests -v
```

## Data dan keterlambatan

- **Saham IDX (Yahoo Finance `.JK`)**: data terlambat sekitar 10 menit.
- **Forex (Yahoo Finance `=X`)**: data bersifat real-time (keterlambatan 0 menit).
- **Gratis dan tidak resmi**: endpoint Yahoo Finance bukan API resmi; data bisa melambat, berubah, atau terkena batas permintaan (rate-limit). Selalu periksa harga langsung di aplikasi broker Anda sebelum bertindak.

## Aturan berubah

Aturan pasar disimpan di `skills\trader-core\markets\`, bukan di dalam skrip:

- **Batas ARA/ARB IDX**: di `skills\trader-core\markets\idx.json`, aturan saat ini berlaku sampai `valid_until` (`2026-12-31`, Peraturan II-A, Kep-00158/BEI/10-2026). Perbarui bagian `auto_rejection` jika BEI mengubah aturan.
- **Hari libur IDX tahunan**: daftar `holidays` dan `calendar_years` (`[2026]`) di `skills\trader-core\markets\idx.json` perlu diperbarui setiap tahun sesuai pengumuman BEI.
- **Profil Forex**: daftar pair, spread bawaan, dan aturan DST berada di `skills\trader-core\markets\fx.json`.

## Ketentuan penting

**Bukan saran investasi / bukan nasihat keuangan.** Perangkat lunak ini hanya membaca data publik dan melakukan perhitungan. Ia tidak mengetahui kondisi keuangan Anda dan tidak bisa meramal masa depan. Sebagian besar pelaku day trading mengalami kerugian. Anda bisa kehilangan uang. Putuskan sendiri, dan konsultasikan dengan penasihat berlisensi jika membutuhkan nasihat.

**Tidak ada order yang berjalan tanpa persetujuan "yes" dari Anda.** Hanya `/trader-broker` yang menyiapkan tiket order, dan hanya setelah `/trader-risk` memberi status PASS serta Anda mengetik `yes` secara eksplisit untuk order tersebut. Semua order selalu manual: Anda sendiri yang memasukkannya ke aplikasi broker. Set izin tool order di Antigravity ke `ask` (jangan `allow`), dan jangan gunakan mode Turbo di workspace trading.

**Paper trading sebagai bawaan.** `"paper": true` dan `"broker": "manual"` adalah bawaan di `config.example.json` maupun `config.fx.example.json`.

**Forex hanya dengan broker berizin Bappebti.** Untuk transaksi forex, gunakan hanya pialang berjangka yang berizin dan diawasi oleh Bappebti (periksa daftar resmi di situs Bappebti sebelum menyetor dana).

**Time Machine adalah simulasi, bukan prediksi.** Hasilnya dibangun dari data 5 menit 60 hari terakhir. Masa depan bisa memunculkan hal baru seperti laporan keuangan, suspensi (halt), atau berita mendadak.

**Stop adalah rencana, bukan jaminan.** Saat pasar bergerak cepat atau terjadi gap (termasuk jeda istirahat siang IDX), harga eksekusi bisa lebih buruk dari harga stop.

**Pajak.** Tidak ada bagian dari perangkat ini yang merupakan saran pajak.

## Kredit

Berdasarkan [Jakeschincariol/day-trader-skill](https://github.com/Jakeschincariol/day-trader-skill) (MIT), upstream commit 3d0f4ef.

## Lisensi

MIT.
