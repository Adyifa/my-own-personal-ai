# AI Voice Assistant Bahasa Indonesia

Assistant Windows sederhana untuk membuka website, aplikasi, folder, atau file dengan perintah bahasa Indonesia.

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

## Settings GUI

Buka dari tray Mika dengan menu `Settings`, atau jalankan:

```powershell
.\run_settings.bat
```

Di Settings kamu bisa mengubah nama assistant, wake phrase, voice preset, voice manual, mic device, responsivitas mic, serta menambah website, aplikasi, game, dan file/folder tanpa edit JSON manual.

Setelah menyimpan perubahan, klik kanan tray Mika lalu pilih `Reload config`.

## Auto-discovery aplikasi dan game

Mika otomatis scan shortcut di Start Menu/Desktop dan mencoba membaca Steam library. Jadi banyak aplikasi bisa langsung dibuka, misalnya:

```text
halo mika buka file explorer
halo mika buka osu
```

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

Upload zip dari `voice_models\_kaggle_exports` ke Kaggle Dataset. Di Kaggle Notebook, upload [kaggle_personal_voice_train.py](./kaggle_personal_voice_train.py), aktifkan GPU, lalu jalankan:

```python
!pip install -q TTS>=0.22.0 torch torchaudio
!python /kaggle/working/kaggle_personal_voice_train.py validate --dataset "/kaggle/input/my-voice-kaggle-dataset/my_voice_kaggle_dataset.zip" --i-own-this-voice
!python /kaggle/working/kaggle_personal_voice_train.py train --dataset "/kaggle/input/my-voice-kaggle-dataset/my_voice_kaggle_dataset.zip" --epochs 1000 --batch-size 8 --mixed-precision --export --i-own-this-voice
```

Download `/kaggle/working/mika_voice_export.zip`, unzip di laptop, lalu apply model dengan command `apply-model` di atas. Detail lengkap ada di [KAGGLE_PERSONAL_VOICE.md](./KAGGLE_PERSONAL_VOICE.md).
