# Panduan Pengguna Mika

Panduan lengkap memakai Mika: perintah suara, tray, settings, build EXE, dan suara personal. Ringkasan proyek ada di [README](../README.md).

## Mode AI (baru)

Perintah yang dikenal (buka youtube, main cs2, sleep laptop, ...) tetap lewat jalur aturan yang cepat dan offline.
Sisanya (pertanyaan, obrolan, "cari resep rendang", "buka yang kedua") dijawab agent LLM dengan tool calling.

1. Pasang [Ollama](https://ollama.com), lalu unduh model lokal (sekitar 2,5 GB, muat di GPU 4 GB):

   ```powershell
   ollama pull qwen3:4b
   ```

2. Opsional: salin `.env.example` menjadi `.env`, lalu isi `OPENAI_API_KEY` (cadangan kalau Ollama mati) dan/atau
   `TAVILY_API_KEY` / `BRAVE_API_KEY` (pencarian web yang lebih andal). Tanpa key, pencarian memakai `ddgs`.
3. Install dependency baru: `python -m pip install -r requirements.txt`
4. Coba tanpa mikrofon dan tanpa suara:

   ```powershell
   python assistant.py --text --mute
   ```

Contoh: `berita teknologi hari ini apa?`, `cari resep rendang`, lalu `buka yang pertama`, `aku lagi capek nih`.
Kalau Ollama dan API sama-sama tidak tersedia, Mika otomatis kembali ke perilaku lama (template dan pencarian di browser).
Pengaturan ada di bagian `llm`, `agent`, dan `web_search` di `commands.json`.

Jalankan test (mikrofon, TTS, dan LLM di-mock):

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest
```

## Skill sehari-hari

Semua ini jalan cepat tanpa AI dan tanpa internet, kecuali cuaca.

| Kategori | Contoh perintah |
|---|---|
| Jam dan tanggal | `jam berapa sekarang`, `hari ini tanggal berapa` |
| Timer | `pasang timer 5 menit buat masak mie`, `sisa timer berapa lagi`, `batalkan timer` |
| Pengingat | `ingatkan aku jam 7 malam minum obat`, `ingatkan aku 30 menit lagi angkat jemuran`, `besok pagi ingatkan aku meeting jam 9` |
| Alarm | `bangunkan aku besok jam 5 pagi`, `pasang alarm jam 6 pagi` |
| Kelola pengingat | `pengingat apa saja`, `hapus pengingat minum obat`, `tunda 10 menit` (setelah pengingat berbunyi) |
| Cuaca | `cuaca hari ini`, `cuaca besok di bandung`, `bakal hujan nggak` |
| Musik | `pause`, `putar lagi`, `lagu berikutnya`, `lagu sebelumnya` |
| Volume | `kecilkan volume`, `volume 50 persen`, `matikan suara`, `nyalakan suara` |
| Laptop | `baterai berapa`, `laptop lagi dicas nggak`, `info sistem` |
| Catatan | `catat beli susu`, `bacakan catatan`, `buka catatan` |

Kalau waktu pengingat belum disebut, Mika bertanya "Mau diingatkan kapan?" dan kamu bisa langsung menjawab tanpa "Halo Mika".
Waktu bisa diucapkan dengan angka atau kata: `jam setengah 8 malam` (19.30), `jam 10 kurang seperempat`, `lima belas menit lagi`.

Pengingat dan catatan disimpan di folder `data/` (tidak ikut Git). Pengingat yang terlewat saat laptop mati akan
diumumkan begitu Mika menyala lagi, selama belum lewat 12 jam.

Atur kota cuaca default di `commands.json`:

```json
"weather": {
  "location": "Bandung",
  "country_code": "ID"
}
```

## Suara offline dan memotong Mika

**Mesin pengenal suara.** Pilih di Settings, tab `Suara & AI`, atau di `commands.json`:

```json
"stt": { "engine": "whisper", "whisper": { "model": "small" } }
```

- `google`: perilaku lama, butuh internet, audio dikirim ke Google.
- `whisper`: offline dan privat, audio tidak keluar dari laptop. Pemakaian pertama mengunduh model
  (`small` sekitar 480 MB, `base` 145 MB, `tiny` 75 MB) ke `C:\Users\<nama>\.cache\huggingface`.
  Kalau LLM lokal (Ollama) memakai GPU 4 GB, Whisper otomatis jalan di CPU.
  Pakai `small`: dari hasil uji, `tiny` memang cepat (±0,25 detik) tapi sering salah dengar bahasa Indonesia.
  Unduh model saat koneksi cepat; jalankan `run_mic_test.bat` sekali untuk memicu unduhannya.

Coba dulu dengan `run_mic_test.bat`: daftar mikrofon, level suara, dan hasil transkrip dengan mesin yang dipilih.

**Memotong Mika (barge-in).** Atur `barge_in.mode`:

| Mode | Cara kerja | Cocok untuk |
|---|---|---|
| `keyword` (default) | Bilang `stop`, `cukup`, `diam`, atau `halo mika, ...` saat Mika bicara. Suara Mika sendiri yang terdengar balik dari speaker diabaikan. | Speaker laptop |
| `voice` | Ucapan apa pun langsung memotong Mika. | Headset |
| `off` | Ucapan saat Mika bicara diabaikan, seperti versi lama. | Ruangan ramai |

Dari tray juga ada menu **Diam (hentikan suara)**.

**Latensi.** Setiap giliran dicatat di `data/latency.jsonl`: waktu pengenalan suara, token pertama LLM, dan suara
pertama Mika, dihitung dari saat kamu selesai bicara.

## Layar, clipboard, briefing, dan memori

| Fitur | Contoh perintah | Catatan |
|---|---|---|
| Lihat layar | `lihat layarku`, `lihat layarku, error ini artinya apa`, `jelaskan jendela ini` | Butuh `ollama pull qwen2.5vl:3b`. Tangkapan layar tidak disimpan dan tidak dikirim ke cloud kecuali diizinkan di Settings. |
| Clipboard | `rangkum yang aku copy`, `terjemahkan yang aku copy ke inggris`, `jelaskan yang aku salin`, `bacakan clipboard` | Hasil terjemahan otomatis disalin ke clipboard. `bacakan` jalan tanpa AI. |
| Briefing | `briefing pagi`, `apa agenda hari ini`, atau `selamat pagi` sebelum pukul 11.00 | Isi: tanggal, cuaca, pengingat hari ini, dua judul berita. |
| Berita | `berita hari ini`, `berita terbaru` | Judul dari Antara, CNN Indonesia, Republika, CNBC Indonesia; tautan tampil di layar. |
| Memori | `ingat bahwa aku suka kopi tanpa gula`, `apa yang kamu ingat tentang aku`, `lupakan soal kopi`, `hapus semua memori` | Disimpan di `data/memory.json` (tidak ikut Git). Menghapus semua butuh jawaban "iya". Password, PIN, OTP, nomor kartu, NIK, dan rekening selalu ditolak. |

Memori dipakai AI saat relevan, misalnya saran makanan memperhitungkan alergi yang pernah kamu sebut.
Setelah AI membaca halaman web, layar, atau clipboard dalam satu giliran, ia tidak boleh menyimpan memori,
supaya teks dari luar tidak bisa menanam "ingatan palsu".

## Cara menjalankan

1. Install Python 3.10 atau lebih baru.
2. Buka terminal di folder ini.
3. Install dependency:

```powershell
python -m pip install -r requirements.txt
```

4. Tes tanpa mikrofon:

```powershell
python assistant.py --text
```

5. Jalankan mode suara:

```powershell
python assistant.py
```

Kamu juga bisa klik `run_text.bat` atau `run_voice.bat`.

## Mode aplikasi background

Jalankan:

```powershell
.\run_background.bat
```

Assistant akan berjalan tanpa terminal dan muncul di system tray Windows. Klik kanan ikon tray untuk:

- `Mulai dengar`
- `Stop dengar`
- `Tes mikrofon`
- `Settings`
- `Buka commands.json`
- `Reload config`
- `Keluar`

Supaya otomatis aktif saat laptop dinyalakan, jalankan:

```powershell
.\install_startup.bat
```

Untuk mematikan auto-start lagi:

```powershell
.\uninstall_startup.bat
```

## Build menjadi EXE

Jalankan:

```powershell
.\build_exe.bat
```

Hasilnya ada di:

```text
dist\MikaAssistant.exe
```

Simpan `commands.json` di folder `dist` bersama exe supaya menu `Buka commands.json` dan setting perintah tetap mudah diedit.

## Kalau assistant tidak mendengar suara

Jalankan:

```powershell
.\run_mic_test.bat
```

Tes ini akan menampilkan daftar microphone dan mencoba mengenali suara. Kalau microphone default salah, edit `commands.json` dan isi `listen.device_index` dengan angka microphone yang benar, lalu klik `Reload config` dari tray.

## Biar terasa responsif

Mika memakai deteksi jeda bicara yang lebih pendek supaya cepat merespons setelah kamu selesai ngomong:

```json
"listen": {
  "ambient_adjust_seconds": 0.15,
  "pause_threshold": 0.45,
  "non_speaking_duration": 0.2
}
```

Kalau Mika terlalu cepat memotong kalimat panjang, naikkan `pause_threshold` ke `0.6` atau `0.7`. Kalau Mika masih terasa lama menjawab, turunkan sedikit ke `0.35`.

## Contoh perintah

- `halo mika buka youtube`
- `ini random halo mika buka youtube`
- `halo mica buka youtube`
- `halo mika cari kucing lucu di youtube`
- `halo mika nonton youtube tentang valorant`
- `halo mika cari cuaca jakarta di google`
- `halo mika buka gmail`
- `halo mika buka notepad`
- `halo mika buka kalkulator`
- `halo mika buka counter strike`
- `halo mika main cs2`
- `halo mika aku mau main cs2 dong`
- `halo mika putar lagu malu malu dari dia dan indahkus di spotify`
- `halo mika puterin lagu yang santai`
- `halo mika buka file laporan`
- `halo mika cari file skripsi revisi`
- `halo mika buka folder downloads`
- `halo mika sleep laptop`
- `halo mika matikan laptop`
- `halo mika bantuan`
- `halo mika keluar`
- `halo mika apa kabar`
- `halo mika ngobrol yuk`
- `halo mika aku lagi capek`
- `halo mika cerita lucu`

### Bahasa santai dan bahasa daerah

Perintah tidak harus baku. Mika merapikan dulu kalimatnya sebelum dicocokkan, tanpa butuh AI, jadi tetap instan dan jalan offline:

- slang Jakarta: `gue mau nonton smitty`, `gw pengen nonton video smitty di yt`, `nyariin…`, `liatin…`, `setelin…`
- sapaan dan partikel: `kak cariin smitty di youtube ya`, `cariin dong video smitty di youtube`, `ane mau nonton smitty gan`
- Sunda: `carikeun video smitty di youtube`, `aing hayang nonton smitty`
- Jawa: `golekno video smitty nang youtube`, `goleki … neng youtube`, `tulung golekke … ning youtube`
- ejaan hasil speech-to-text: `yutub`, `you tube`, `yt`, dan titik di akhir kalimat
- perintah lain: `matiin laptop dong`, `berhentiin lagunya`, `lanjutin lagunya`, `pelanin suaranya ya`, `buka youtube terus cari smitty`

Isi catatan, pengingat, dan ingatan tetap disimpan persis seperti yang kamu ucapkan: `kak catat liat jadwal kuliah ya` tersimpan sebagai "liat jadwal kuliah".

Kalimat utuh dalam bahasa daerah yang tidak dikenali aturan diteruskan ke AI, jadi butuh model (Ollama atau API key) yang tersambung.

## Kalau kamu sedang tidak baik-baik saja

Kalau kamu bilang hal seperti `aku pengen mati aja` atau `aku capek hidup`, Mika tidak menjalankan perintah apa pun. Mika menjawab dengan kalimat tetap yang hati-hati, menyebut nomor layanan (SEJIWA 119 ekstensi 8, darurat 112), menampilkannya di layar, dan tetap mendengarkan tanpa perlu kata panggil. Ini berlaku juga saat Mika offline. Nomor layanan bisa diubah di bagian `safety` pada `commands.json` (`crisis_call` dan `crisis_lines`). Periksa sesekali apakah nomornya masih berlaku.

## Aksi penting pakai konfirmasi

Perintah seperti shutdown, restart, sleep, lock, dan logout tidak langsung dijalankan. Mika akan bertanya konfirmasi dulu.

Contoh:

```text
halo mika matikan laptop
```

Mika akan menjawab:

```text
Yakin? Bilang iya untuk lanjut. Kalau tidak, bilang batal.
```

Jawab `iya` untuk lanjut, atau `batal` untuk membatalkan.

Perintah yang dinegasikan atau berupa pertanyaan tidak pernah dijalankan: `jangan matikan laptop` dijawab "Oke", `cara matikan laptop yang benar` diteruskan ke AI. Mika juga belum bisa menjadwalkan: `matikan laptop 30 menit lagi` tidak langsung mematikan laptop, Mika menjelaskan bahwa kamu perlu bilang `matikan laptop` saat sudah waktunya.

Jawaban santai juga dimengerti. Untuk lanjut, semua katanya harus setuju: `iya mika`, `oke gas`, `yakin`. Untuk batal, cukup satu kata penolakan: `gak jadi deh`, `nggak usah`, `jangan dulu`, `batalin aja`. Jawaban yang ragu seperti `ya udah` atau `iya tapi nanti` membuat Mika bertanya lagi, dan aksinya batal sendiri kalau tidak dijawab dalam beberapa detik.

## Cek dan bersihkan disk

Tanya kenapa disk penuh, Mika mengukurnya tanpa menghapus apa pun:

```text
halo mika kenapa disk c-ku penuh
halo mika cek detail disk
```

Yang pertama selesai dalam beberapa detik: Mika menyebut cache terbesar yang bisa dibersihkan, dan daftar lengkapnya muncul di layar. `cek detail disk` mengukur semua folder (paling lama satu menit).

Untuk membersihkan:

```text
halo mika hapus cache nvidia
halo mika bersihin cache
halo mika hapus file sementara
```

- Yang boleh dihapus hanya daftar cache tetap: cache shader NVIDIA dan DirectX, file sementara (Temp), cache npm dan pip, crash dump, dan unduhan lama Windows Update. Downloads, Documents, game, aplikasi, tempat sampah, dan file sistem tidak pernah disentuh.
- Mika menyebut apa dan berapa besar yang akan dihapus, rinciannya muncul di layar, lalu menunggu `iya`. Penghapusannya permanen.
- File yang sedang dipakai (misalnya cache game yang sedang jalan) dilewati.
- Folder yang butuh hak admin (Windows Temp, cache Windows Update) dibersihkan lewat jendela izin Windows (UAC): klik `Yes`. Kalau ditolak, bagian itu dilewati. Matikan dengan `"admin_cleanup": false` di bagian `disk` pada `commands.json`.
- AI-nya hanya bisa mengukur disk, tidak bisa menghapus. Penghapusan selalu lewat perintah di atas.
- Cache NVIDIA akan terisi lagi sampai batasnya. Supaya tidak cepat penuh, kecilkan batasnya di NVIDIA Control Panel → Manage 3D Settings → Shader Cache Size.

## Wake phrase live

Mika mendengarkan dalam potongan pendek. Dia mengabaikan suara biasa, lalu mulai memproses ketika mendengar wake phrase seperti:

- `halo mika`
- `hai mika`
- `hey mika`
- `halo mica`
- `halo nika`

Wake phrase boleh muncul di tengah transcript. Jadi kalau speech recognition menangkap:

```text
ada suara lain halo mika buka youtube
```

Mika akan mengambil bagian setelah wake phrase:

```text
buka youtube
```

Kalau kamu cuma bilang `halo mika`, Mika akan menjawab dan menunggu perintah lanjutan beberapa detik. `Halo zeta` masih disimpan sementara sebagai fallback lama.

## Ngobrol ringan

Mika bisa merespons obrolan pendek tanpa membuka aplikasi. Contoh:

```text
halo mika apa kabar
halo mika siapa kamu
halo mika aku bosan
halo mika aku lagi stres
halo mika temenin aku
halo mika kamu bisa apa
```

Kalau kamu bilang `halo mika ngobrol yuk`, Mika mengaktifkan mode ngobrol sebentar. Selama beberapa detik setelah itu kamu bisa lanjut bicara tanpa mengulang wake word. Untuk menutupnya:

```text
selesai ngobrol
```

Mode ngobrol ini tetap pendek supaya Mika tidak terlalu sensitif menangkap suara random.

## Kepribadian Mika

Cara Mika bicara diatur sekali dan berlaku untuk semua fitur: balasan tetap, konfirmasi, pesan error, curhat, dan jawaban AI. Buka Settings, lalu tab **Kepribadian**:

- **Panggil aku**: namamu, misalnya `Yasa`. Mika memakainya saat menyapa dan berterima kasih ("Halo Yasa, Mika di sini.").
- **Gaya bahasa**: `santai` (aku-kamu), `gaul` (gue-lo), atau `sopan` (saya-Anda, bahasa baku).
- **Saat curhat**: `tanya_dulu` (Mika tanya dulu kamu mau saran atau cuma didengar), `langsung`, atau `dengar_saja`.
- **Humor**: `tidak`, `sedikit`, atau `banyak`. Mika berhenti bercanda saat kamu sedih atau serius.

Keputusan selalu di tanganmu: kalau Mika memberi saran, bentuknya pilihan beserta untung-ruginya.

### Curhat

Kamu bisa cerita soal kerjaan, kuliah, pacar, keluarga, teman, atau perasaanmu. Mika masuk **mode curhat**:

- Mika menanggapi perasaanmu dulu, bertanya paling banyak satu hal, dan tidak menghakimi siapa pun.
- Saran mengikuti pengaturan "Saat curhat" di tab Kepribadian. Kalau Mika memberi saran, bentuknya dua atau tiga pilihan beserta untung-ruginya, dan keputusan dikembalikan ke kamu.
- Selama curhat, Mika tidak mencari di web atau membuka aplikasi kecuali kamu memintanya. Perintah seperti `pasang timer 5 menit` tetap jalan.
- Selama sekitar 45 detik setelah tiap balasan, kamu bisa lanjut bercerita tanpa kata panggil. Kalimat lanjutan seperti "dia nggak pernah dengerin aku" tetap dianggap bagian dari cerita. Bilang `selesai ngobrol` untuk menutup.

**Privasi:** curhat hanya diproses model AI lokal (Ollama) di laptop ini. Curhat tidak dikirim ke AI cloud, dan tidak ikut terbawa ketika kamu bertanya hal lain yang dijawab AI cloud. Kalau mau mengizinkan cloud, centang "Izinkan curhat diproses AI cloud" di tab Kepribadian.

Kalau model lokal belum terpasang, Mika bilang sekali bahwa otak AI lokalnya belum aktif, lalu tetap mendengarkan dengan balasan yang lembut. Untuk mengaktifkan, pasang Ollama lalu jalankan `ollama pull qwen3:4b`. Ingatan percakapan menyusul di tahap berikutnya.

### Dua perintah sekaligus

Sambungkan dengan `terus`, `lalu`, `habis itu`, atau `kemudian` (atau `dan`, kalau dua-duanya perintah):

```text
halo mika matikan suara terus kunci laptop
halo mika buka spotify terus putar lagu tulus
halo mika catat beli susu dan ingatkan jam 5
```

Mika menjalankannya berurutan. Aksi yang butuh konfirmasi (shutdown, kunci laptop, hapus cache) hanya boleh di urutan terakhir, dan catatan yang isinya mengandung kata `terus` tetap jadi satu catatan. Kalau aplikasi Spotify terpasang, pencarian lagu langsung dibuka di aplikasinya.

## Settings GUI

Buka dari tray Mika dengan menu `Settings`, atau jalankan:

```powershell
.\run_settings.bat
```

Di Settings kamu bisa mengubah nama assistant, wake phrase, voice preset, voice manual, mic device, responsivitas mic, serta menambah website, aplikasi, game, dan file/folder tanpa edit JSON manual.

Setelah menyimpan perubahan, klik kanan tray Mika lalu pilih `Reload config`.

## Auto-discovery aplikasi dan game

Mika otomatis scan shortcut di Start Menu/Desktop, aplikasi Microsoft Store (lewat `Get-StartApps`, misalnya WhatsApp, Spotify, Settings, Camera, Netflix), dan mencoba membaca Steam library. Jadi semua aplikasi yang muncul di Start Menu bisa langsung dibuka tanpa klik atau cari, misalnya:

```text
halo mika buka file explorer
halo mika buka whatsapp
halo mika buka spotify
halo mika buka osu
```

Beberapa sebutan Indonesia dan singkatan juga dikenali, asal aplikasinya terpasang: `pengaturan`/`setelan` (Settings), `kamera`, `foto`/`galeri` (Photos), `wa` (WhatsApp), `vs code`, `store` (Microsoft Store), `pengelola tugas` (Task Manager).

`buka spotify` membuka aplikasi Spotify (atau web player kalau aplikasinya tidak ada), sedangkan `putar lagu X di spotify` tetap mencari lagu.

Scan aplikasi Store berjalan di belakang saat Mika start (sekitar 1 detik). Matikan dengan `"scan_store_apps": false` di bagian `auto_discovery` pada `commands.json` kalau tidak dibutuhkan.

Kalau aplikasi/game tidak ketemu, tambahkan manual lewat Settings atau `commands.json`.

## Mengatur website, aplikasi, dan file

Edit `commands.json`.

Contoh tambah website:

```json
"websites": {
  "youtube": "https://www.youtube.com",
  "kampus": "https://nama-website-kampus.ac.id"
}
```

Contoh tambah file:

```json
"files": {
  "skripsi": "C:/Users/YSLRS/Documents/skripsi.docx"
}
```

Contoh tambah aplikasi:

```json
"apps": {
  "word": "winword.exe",
  "excel": "excel.exe"
}
```

Contoh tambah game Steam:

```json
"games": {
  "counter strike": "steam://rungameid/730",
  "dota": "steam://rungameid/570"
}
```

Contoh tambah game dari file `.exe`:

```json
"games": {
  "game lokal": "D:/Games/Nama Game/Game.exe"
}
```

Contoh tambah alias lagu Spotify:

```json
"music": {
  "provider": "spotify",
  "open_mode": "web",
  "songs": {
    "malu malu": "Malu Malu Dia Indahkus"
  }
}
```

## Suara Character AI

Project ini default memakai suara neural Indonesia lewat `edge-tts`, jadi lebih natural daripada text-to-speech Windows bawaan. Setting default dibuat agak lebih imut:

```json
"voice": {
  "provider": "edge",
  "edge_voice": "id-ID-GadisNeural",
  "edge_rate": "+12%",
  "edge_pitch": "+10Hz"
}
```

Kamu bisa pilih preset dari Settings:

- `cute`: lebih imut, cepat sedikit, pitch naik
- `soft`: lembut dan natural
- `calm`: lebih pelan dan tenang
- `anime`: lebih ceria dan anime-ish, tapi tetap original Mika
- `custom`: pakai setting manual yang kamu isi sendiri

Preset juga mengubah gaya jawaban Mika, misalnya:

```text
Iya, Mika denger.
Oke, Mika bukain YouTube ya.
Sebentar, Mika cari musik santai di YouTube.
```

Untuk suara laki-laki Indonesia, ganti `edge_voice` menjadi:

```json
"edge_voice": "id-ID-ArdiNeural"
```

Lihat daftar voice neural Indonesia:

```powershell
python list_neural_voices.py
```

Kalau mau kembali ke suara Windows bawaan, isi:

```json
"provider": "sapi"
```

Saat memakai `provider: "sapi"`, suara yang tersedia tergantung voice yang terpasang di Windows. Kamu bisa pilih voice dengan mengisi `voice.name_contains` di `commands.json`, misalnya `"indonesia"` atau bagian nama voice lain yang muncul di Windows.

Lihat daftar voice yang tersedia:

```powershell
python list_voices.py
```

Voice dari Character.AI tidak dipakai langsung di sini karena integrasi suara Character.AI tidak tersedia sebagai API resmi umum untuk assistant lokal. Kalau kamu ingin suara yang lebih mirip karakter, opsi yang lebih rapi adalah memakai voice TTS resmi seperti Windows Indonesian voice, ElevenLabs, Azure Speech, Google Cloud TTS, atau OpenAI TTS, selama kamu punya izin untuk suara/karakter yang dipakai.

## Voice Tone Trainer

Project ini juga punya tone trainer legal untuk mengatur suara Mika dari rekaman yang kamu punya izin. Ini bukan voice cloning dan tidak meniru identitas suara orang/karakter. Yang dianalisis hanya tone/prosody sederhana seperti pitch, tempo, jeda, dan energi.

Rekam sample suara:

```powershell
python voice_tone_trainer.py record --name my_voice --seconds 45 --i-have-rights
```

Analisis sample dan langsung apply ke `commands.json`:

```powershell
python voice_tone_trainer.py analyze --name my_voice --apply --i-have-rights
```

Kalau sudah punya WAV sendiri:

```powershell
python voice_tone_trainer.py analyze --name my_voice --samples "C:\path\ke\folder_wav" --apply --i-have-rights
```

Hasil profile tersimpan di:

```text
voice_profiles\my_voice\profile.json
```

Setelah apply, klik kanan tray Mika lalu pilih `Reload config`. Kalau hasilnya terlalu cempreng atau terlalu rendah, buka Settings dan tweak `Voice pitch` / `Voice rate`.

## Personal Voice Model

Kalau suaranya adalah suara kamu sendiri, kamu bisa membuat dataset dan training model personal. Ini jauh lebih berat daripada tone trainer: butuh banyak sample bersih, waktu lama, dan idealnya GPU NVIDIA/CUDA.

Install dependency opsional:

```powershell
python -m pip install -r requirements_personal_voice.txt
```

Lihat microphone:

```powershell
python personal_voice_recorder.py list-devices
```

Rekam dataset dari prompt Indonesia:

```powershell
python personal_voice_recorder.py record --name my_voice --seconds-per-prompt 7 --i-own-this-voice
```

Rapikan dataset dan buat metadata:

```powershell
python personal_voice_recorder.py prepare --name my_voice --i-own-this-voice
```

Training VITS dari dataset:

```powershell
python personal_voice_train_vits.py train --name my_voice --epochs 1000 --batch-size 8 --i-own-this-voice
```

Tes checkpoint hasil training:

```powershell
python personal_voice_train_vits.py synthesize --model-path "C:\path\best_model.pth" --config-path "C:\path\config.json" --text "Halo, aku Mika." --i-own-this-voice
```

Pakai model hasil training di Mika:

```powershell
python personal_voice_train_vits.py apply-model --model-path "C:\path\best_model.pth" --config-path "C:\path\config.json" --i-own-this-voice
```

Mode cepat tanpa training penuh, pakai XTTS reference voice dari WAV kamu sendiri:

```powershell
python personal_voice_train_vits.py apply-xtts --speaker-wav "C:\path\suara_kamu.wav" --i-own-this-voice
```

Setelah apply, klik kanan tray Mika lalu pilih `Reload config`. Untuk menjalankan provider Coqui/XTTS dari Python, jalankan Mika dengan:

```powershell
python tray_assistant.py
```

Catatan: membundel PyTorch/TTS ke `.exe` bisa sangat besar dan sering rewel, jadi mode personal voice lokal paling stabil dijalankan lewat Python dulu.

## Training di Kaggle

Kalau laptop tidak kuat training, package dataset untuk Kaggle:

```powershell
python personal_voice_recorder.py package-kaggle --name my_voice --i-own-this-voice
```

Upload zip dari `voice_models\_kaggle_exports` ke Kaggle Dataset. Di Kaggle Notebook, upload [kaggle_personal_voice_train.py](../kaggle_personal_voice_train.py), aktifkan GPU, lalu jalankan:

```python
!pip install -q TTS>=0.22.0 torch torchaudio
!python /kaggle/working/kaggle_personal_voice_train.py validate --dataset "/kaggle/input/my-voice-kaggle-dataset/my_voice_kaggle_dataset.zip" --i-own-this-voice
!python /kaggle/working/kaggle_personal_voice_train.py train --dataset "/kaggle/input/my-voice-kaggle-dataset/my_voice_kaggle_dataset.zip" --epochs 1000 --batch-size 8 --mixed-precision --export --i-own-this-voice
```

Download `/kaggle/working/mika_voice_export.zip`, unzip di laptop, lalu apply model dengan command `apply-model` di atas. Detail lengkap ada di [KAGGLE_PERSONAL_VOICE.md](../KAGGLE_PERSONAL_VOICE.md).
