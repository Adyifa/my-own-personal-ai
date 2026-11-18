from __future__ import annotations

import copy
import json
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from ..config import CONFIG_PATH, DEFAULT_CONFIG, apply_personality_preset, deep_merge
from ..persona import VOICE_PERSONALITY_PRESETS


class SettingsWindow:
    def __init__(self, config_path: Path):
        self.config_path = config_path
        self.root = tk.Tk()
        self.root.title("Mika Settings")
        self.root.geometry("760x620")
        self.root.minsize(680, 540)
        self.config = self.load_config()

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=10)

        self.general_tab = ttk.Frame(self.notebook)
        self.shortcuts_tab = ttk.Frame(self.notebook)
        self.raw_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.general_tab, text="General")
        self.notebook.add(self.shortcuts_tab, text="Shortcuts")
        self.notebook.add(self.raw_tab, text="Raw JSON")

        self.build_general_tab()
        self.build_shortcuts_tab()
        self.build_raw_tab()
        self.build_footer()
        self.load_values()

    def load_config(self) -> dict[str, Any]:
        if not self.config_path.exists():
            return apply_personality_preset(copy.deepcopy(DEFAULT_CONFIG))
        with self.config_path.open("r", encoding="utf-8") as config_file:
            return apply_personality_preset(deep_merge(DEFAULT_CONFIG, json.load(config_file)))

    def build_general_tab(self) -> None:
        frame = ttk.Frame(self.general_tab, padding=12)
        frame.pack(fill="both", expand=True)

        self.assistant_name = tk.StringVar()
        self.personality_preset = tk.StringVar()
        self.wake_enabled = tk.BooleanVar()
        self.wake_phrases = tk.StringVar()
        self.edge_voice = tk.StringVar()
        self.edge_rate = tk.StringVar()
        self.edge_pitch = tk.StringVar()
        self.mic_device = tk.StringVar()
        self.ambient_adjust = tk.StringVar()
        self.pause_threshold = tk.StringVar()
        self.non_speaking_duration = tk.StringVar()

        ttk.Label(frame, text="Voice preset").grid(row=0, column=0, sticky="w", pady=6)
        preset_box = ttk.Combobox(
            frame,
            textvariable=self.personality_preset,
            values=["cute", "soft", "calm", "anime", "custom"],
            state="readonly",
            width=20,
        )
        preset_box.grid(row=0, column=1, sticky="w", pady=6)
        preset_box.bind("<<ComboboxSelected>>", self.on_preset_select)

        rows = [
            ("Nama assistant", self.assistant_name),
            ("Wake phrases", self.wake_phrases),
            ("Edge voice", self.edge_voice),
            ("Voice rate", self.edge_rate),
            ("Voice pitch", self.edge_pitch),
            ("Mic device index", self.mic_device),
            ("Mic ambient adjust", self.ambient_adjust),
            ("Mic pause threshold", self.pause_threshold),
            ("Mic non-speaking", self.non_speaking_duration),
        ]
        for row, (label, var) in enumerate(rows, start=1):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=6)
            ttk.Entry(frame, textvariable=var, width=48).grid(row=row, column=1, sticky="ew", pady=6)

        ttk.Checkbutton(frame, text="Wake word aktif", variable=self.wake_enabled).grid(
            row=len(rows) + 1, column=1, sticky="w", pady=8
        )
        ttk.Label(
            frame,
            text="Pisahkan wake phrases dengan koma. Contoh: halo mika, hai mika, hey mika",
            foreground="#555",
        ).grid(row=len(rows) + 2, column=1, sticky="w")

        frame.columnconfigure(1, weight=1)

    def build_shortcuts_tab(self) -> None:
        frame = ttk.Frame(self.shortcuts_tab, padding=12)
        frame.pack(fill="both", expand=True)

        self.kind = tk.StringVar(value="websites")
        self.alias = tk.StringVar()
        self.target = tk.StringVar()

        ttk.Label(frame, text="Jenis").grid(row=0, column=0, sticky="w", pady=6)
        ttk.Combobox(
            frame,
            textvariable=self.kind,
            values=["websites", "apps", "games", "files"],
            state="readonly",
            width=20,
        ).grid(row=0, column=1, sticky="w", pady=6)

        ttk.Label(frame, text="Alias").grid(row=1, column=0, sticky="w", pady=6)
        ttk.Entry(frame, textvariable=self.alias).grid(row=1, column=1, columnspan=2, sticky="ew", pady=6)

        ttk.Label(frame, text="Target").grid(row=2, column=0, sticky="w", pady=6)
        ttk.Entry(frame, textvariable=self.target).grid(row=2, column=1, sticky="ew", pady=6)
        ttk.Button(frame, text="Browse", command=self.browse_target).grid(row=2, column=2, padx=(8, 0), pady=6)

        ttk.Button(frame, text="Tambah / Update", command=self.add_shortcut).grid(
            row=3, column=1, sticky="w", pady=10
        )

        self.shortcuts_list = tk.Listbox(frame, height=16)
        self.shortcuts_list.grid(row=4, column=0, columnspan=3, sticky="nsew", pady=(12, 0))
        self.shortcuts_list.bind("<<ListboxSelect>>", self.on_shortcut_select)

        ttk.Button(frame, text="Hapus pilihan", command=self.delete_selected_shortcut).grid(
            row=5, column=1, sticky="w", pady=10
        )

        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(4, weight=1)

    def build_raw_tab(self) -> None:
        self.raw_text = tk.Text(self.raw_tab, wrap="none")
        self.raw_text.pack(fill="both", expand=True, padx=12, pady=12)

    def build_footer(self) -> None:
        footer = ttk.Frame(self.root, padding=(10, 0, 10, 10))
        footer.pack(fill="x")
        ttk.Button(footer, text="Reload dari file", command=self.reload).pack(side="left")
        ttk.Button(footer, text="Save", command=self.save).pack(side="right")

    def load_values(self) -> None:
        self.assistant_name.set(str(self.config.get("assistant_name", "Mika")))
        personality = self.config.get("personality", {})
        self.personality_preset.set(str(personality.get("preset", "cute")))
        self.wake_enabled.set(bool(self.config.get("wake", {}).get("enabled", True)))
        self.wake_phrases.set(", ".join(self.config.get("wake", {}).get("phrases", [])))
        voice = self.config.get("voice", {})
        self.edge_voice.set(str(voice.get("edge_voice", "id-ID-GadisNeural")))
        self.edge_rate.set(str(voice.get("edge_rate", "+12%")))
        self.edge_pitch.set(str(voice.get("edge_pitch", "+10Hz")))
        device = self.config.get("listen", {}).get("device_index")
        self.mic_device.set("" if device is None else str(device))
        listen = self.config.get("listen", {})
        self.ambient_adjust.set(str(listen.get("ambient_adjust_seconds", 0.15)))
        self.pause_threshold.set(str(listen.get("pause_threshold", 0.45)))
        self.non_speaking_duration.set(str(listen.get("non_speaking_duration", 0.2)))
        self.refresh_shortcuts()
        self.refresh_raw()

    def apply_form_values(self) -> None:
        self.config["assistant_name"] = self.assistant_name.get().strip() or "Mika"
        self.config.setdefault("personality", {})["preset"] = self.personality_preset.get().strip() or "cute"
        self.config.setdefault("wake", {})["enabled"] = self.wake_enabled.get()
        self.config["wake"]["phrases"] = [
            phrase.strip() for phrase in self.wake_phrases.get().split(",") if phrase.strip()
        ]
        self.config.setdefault("voice", {})["edge_voice"] = self.edge_voice.get().strip() or "id-ID-GadisNeural"
        self.config["voice"]["edge_rate"] = self.edge_rate.get().strip() or "+12%"
        self.config["voice"]["edge_pitch"] = self.edge_pitch.get().strip() or "+10Hz"
        mic_value = self.mic_device.get().strip()
        self.config.setdefault("listen", {})["device_index"] = int(mic_value) if mic_value else None
        self.config["listen"]["ambient_adjust_seconds"] = float(self.ambient_adjust.get().strip() or 0.15)
        self.config["listen"]["pause_threshold"] = float(self.pause_threshold.get().strip() or 0.45)
        self.config["listen"]["non_speaking_duration"] = float(self.non_speaking_duration.get().strip() or 0.2)

    def on_preset_select(self, event=None) -> None:
        preset = self.personality_preset.get().strip() or "cute"
        if preset != "custom":
            preset_config = VOICE_PERSONALITY_PRESETS.get(preset, VOICE_PERSONALITY_PRESETS["cute"])
            voice = preset_config.get("voice", {})
            self.edge_voice.set(str(voice.get("edge_voice", self.edge_voice.get())))
            self.edge_rate.set(str(voice.get("edge_rate", self.edge_rate.get())))
            self.edge_pitch.set(str(voice.get("edge_pitch", self.edge_pitch.get())))
            self.config.setdefault("voice", {}).update(voice)
            self.config.setdefault("personality", {}).update(preset_config.get("personality", {}))
        self.config.setdefault("personality", {})["preset"] = preset
        self.refresh_raw()

    def browse_target(self) -> None:
        path = filedialog.askopenfilename()
        if path:
            self.target.set(path)

    def add_shortcut(self) -> None:
        alias = self.alias.get().strip()
        target = self.target.get().strip()
        kind = self.kind.get()
        if not alias or not target:
            messagebox.showwarning("Belum lengkap", "Alias dan target harus diisi.")
            return
        self.config.setdefault(kind, {})[alias] = target
        self.alias.set("")
        self.target.set("")
        self.refresh_shortcuts()
        self.refresh_raw()

    def on_shortcut_select(self, event=None) -> None:
        selection = self.shortcuts_list.curselection()
        if not selection:
            return
        value = self.shortcuts_list.get(selection[0])
        kind, rest = value.split(" | ", 1)
        alias, target = rest.split(" -> ", 1)
        self.kind.set(kind)
        self.alias.set(alias)
        self.target.set(target)

    def delete_selected_shortcut(self) -> None:
        selection = self.shortcuts_list.curselection()
        if not selection:
            return
        value = self.shortcuts_list.get(selection[0])
        kind, rest = value.split(" | ", 1)
        alias = rest.split(" -> ", 1)[0]
        self.config.get(kind, {}).pop(alias, None)
        self.refresh_shortcuts()
        self.refresh_raw()

    def refresh_shortcuts(self) -> None:
        self.shortcuts_list.delete(0, tk.END)
        for kind in ["websites", "apps", "games", "files"]:
            for alias, target in sorted(self.config.get(kind, {}).items()):
                self.shortcuts_list.insert(tk.END, f"{kind} | {alias} -> {target}")

    def refresh_raw(self) -> None:
        self.raw_text.delete("1.0", tk.END)
        self.raw_text.insert(tk.END, json.dumps(self.config, indent=2, ensure_ascii=False))

    def reload(self) -> None:
        self.config = self.load_config()
        self.load_values()

    def save(self) -> None:
        try:
            raw_config = json.loads(self.raw_text.get("1.0", tk.END))
        except json.JSONDecodeError as exc:
            messagebox.showerror("JSON salah", str(exc))
            return
        self.config = deep_merge(self.config, raw_config)
        self.apply_form_values()
        self.config_path.write_text(
            json.dumps(self.config, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        self.refresh_raw()
        messagebox.showinfo("Saved", "Config disimpan. Klik Reload config di tray Mika.")

    def run(self) -> None:
        self.root.mainloop()


def open_settings_window(config_path: Path) -> None:
    SettingsWindow(config_path).run()


def main() -> int:
    open_settings_window(CONFIG_PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
