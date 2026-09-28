# Kaggle Personal Voice Training

Panduan ini untuk training suara **kamu sendiri** di Kaggle. Jangan upload suara orang lain/karakter tanpa izin.

## 1. Siapkan dataset di laptop

Rekam dan prepare dataset:

```powershell
python personal_voice_recorder.py record --name my_voice --seconds-per-prompt 7 --i-own-this-voice
python personal_voice_recorder.py prepare --name my_voice --i-own-this-voice
```

Zip dataset untuk Kaggle:

```powershell
python personal_voice_recorder.py package-kaggle --name my_voice --i-own-this-voice
```

File zip akan muncul di:

```text
voice_models\_kaggle_exports\my_voice_kaggle_dataset.zip
```

## 2. Upload ke Kaggle

1. Buka Kaggle.
2. Buat Dataset baru.
3. Upload `my_voice_kaggle_dataset.zip`.
4. Buat Notebook baru.
5. Aktifkan GPU accelerator.
6. Add Data, pilih dataset suara kamu.
7. Upload file [kaggle_personal_voice_train.py](./kaggle_personal_voice_train.py) ke Notebook Files, atau copy isinya ke notebook.

## 3. Install dependency di Kaggle

Di cell Kaggle:

```python
!pip install -q TTS>=0.22.0 torch torchaudio
```

Restart session kalau Kaggle minta.

## 4. Train

Cari path dataset di Kaggle. Biasanya seperti:

```text
/kaggle/input/my-voice-kaggle-dataset/my_voice_kaggle_dataset.zip
```

Validasi dulu:

```python
!python /kaggle/working/kaggle_personal_voice_train.py validate \
  --dataset "/kaggle/input/my-voice-kaggle-dataset/my_voice_kaggle_dataset.zip" \
  --i-own-this-voice
```

Jalankan:

```python
!python /kaggle/working/kaggle_personal_voice_train.py train \
  --dataset "/kaggle/input/my-voice-kaggle-dataset/my_voice_kaggle_dataset.zip" \
  --epochs 1000 \
  --batch-size 8 \
  --mixed-precision \
  --export \
  --i-own-this-voice
```

Kalau VRAM error, turunkan batch:

```python
--batch-size 4
```

## 5. Download hasil

Hasil export:

```text
/kaggle/working/mika_voice_export.zip
```

Download zip itu dari panel output Kaggle.

## 6. Apply di laptop

Unzip hasil Kaggle, lalu jalankan:

```powershell
python personal_voice_train_vits.py apply-model --model-path "C:\path\best_model.pth" --config-path "C:\path\config.json" --i-own-this-voice
```

Lalu jalankan Mika via Python:

```powershell
python tray_assistant.py
```

Catatan: provider personal voice berbasis PyTorch/TTS lebih stabil lewat Python daripada `.exe`.

## Mode cepat tanpa training Kaggle

Kalau mau coba cepat dulu, pakai XTTS reference voice dari 1 WAV suara kamu:

```powershell
python personal_voice_train_vits.py apply-xtts --speaker-wav "C:\path\suara_kamu.wav" --i-own-this-voice
python tray_assistant.py
```
