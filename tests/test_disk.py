"""Disk check and cache cleanup: only listed folders, never through links, admin parts via one elevation."""

from __future__ import annotations

import json
import os
import sys
from types import SimpleNamespace

import pytest

from mika.app import build_assistant
from mika.brain.router import Router
from mika.brain.toolset import build_beyond_tools
from mika.skills import disk as disk_module
from mika.skills.disk import (
    CacheFolder,
    CleanupPlan,
    CleanupResult,
    DiskCare,
    DiskReport,
    Measured,
    ReportItem,
    UnsafeTarget,
    admin_clean_main,
    cache_folders,
    cleanup_question,
    cleanup_summary,
    empty_folder,
    measure,
    report_text,
    run_elevated,
    speak_size,
)
from mika.text import clean_conversational_command
from tests.fakes import FakeSearcher, FakeSpeaker, RecordingLauncher, ScriptedLLM

GB = 1024**3
windows_only = pytest.mark.skipif(sys.platform != "win32", reason="junctions are a Windows feature")


def junction(link, target) -> None:
    """A directory junction (no admin needed), the kind of link that would trick a naive cleaner."""
    import _winapi

    _winapi.CreateJunction(str(target), str(link))


@pytest.fixture
def pc(tmp_path):
    """A fake laptop under tmp_path: user caches, Windows caches, and user files that must never be touched."""
    home = tmp_path / "Users" / "budi"
    local = home / "AppData" / "Local"
    windows = tmp_path / "Windows"
    env = {
        "USERPROFILE": str(home),
        "LOCALAPPDATA": str(local),
        "PROGRAMDATA": str(tmp_path / "ProgramData"),
        "SystemRoot": str(windows),
    }

    def put(path, size: int):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * size)
        return path

    put(local / "NVIDIA" / "DXCache" / "a.bin", 3000)
    put(local / "NVIDIA" / "DXCache" / "sub" / "b.bin", 2000)
    put(local / "Temp" / "t.tmp", 500)
    put(local / "npm-cache" / "_cacache" / "x", 1000)
    put(windows / "Temp" / "w.tmp", 700)
    put(home / "Documents" / "skripsi.docx", 4000)
    put(home / "Downloads" / "setup.exe", 800)
    return SimpleNamespace(tmp=tmp_path, home=home, local=local, windows=windows, env=env, put=put)


@pytest.fixture
def elevations():
    return []


@pytest.fixture
def care(pc, config, elevations):
    config["disk"]["drive"] = str(pc.tmp)  # never stat the real C:\pagefile.sys in tests

    def fake_elevate(categories):
        elevations.append(list(categories))
        return "done", 700, 0

    usage = SimpleNamespace(total=100 * GB, used=93 * GB, free=7 * GB)
    return DiskCare(config, env=pc.env, home=pc.home, disk_usage=lambda drive: usage, elevate=fake_elevate,
                    data_dir=pc.tmp / "data")


# The fixed list -------------------------------------------------------------------------------


def test_tampered_environment_is_not_trusted(pc):
    tampered = {**pc.env, "LOCALAPPDATA": str(pc.tmp), "SystemRoot": "C:\\"}  # "Temp" must never become C:\Temp
    folders = cache_folders(tampered)
    assert all(folder.admin for folder in folders)  # no user-level folders from a bad LOCALAPPDATA
    assert not any(folder.category == "temp" for folder in folders)


def test_list_covers_the_nvidia_caches(pc):
    paths = {str(folder.path) for folder in cache_folders(pc.env) if folder.category == "nvidia"}
    assert str(pc.local / "NVIDIA" / "DXCache") in paths and str(pc.local / "NVIDIA" / "GLCache") in paths


# Measuring --------------------------------------------------------------------------------------


def test_quick_report_measures_the_listed_folders(care):
    report = care.quick_report()
    sizes = {item.label: item.size.bytes for item in report.items}
    assert sizes["cache shader NVIDIA"] == 5000
    assert sizes["file sementara"] == 1200  # user Temp + Windows Temp
    assert sizes["cache npm"] == 1000
    assert sizes["Documents"] == 4000 and sizes["Downloads"] == 800
    assert {item.kind for item in report.items if item.label == "Documents"} == {"user"}
    assert report.free == 7 * GB


@windows_only
def test_measure_never_follows_links(pc):
    outside = pc.put(pc.tmp / "outside" / "big.bin", 9000).parent
    junction(pc.local / "NVIDIA" / "DXCache" / "loop", outside)
    assert measure(pc.local / "NVIDIA" / "DXCache").bytes == 5000


def test_deep_report_lists_every_top_folder(care, pc):
    report = care.deep_report()
    kinds = {item.label: item.kind for item in report.items}
    assert {"Windows", "Documents", "Downloads", "cache shader NVIDIA"} <= set(kinds)
    assert kinds["AppData NVIDIA"] == "mostly_cache"  # the folder is all shader cache, not "kept" data
    assert kinds["Documents"] == "user" and report.deep
    spoken, detail = report_text(report)
    assert "AppData NVIDIA" not in spoken  # the voice names real folders and gives the cache total separately


# Speech and screen text --------------------------------------------------------------------------


def make_report(*items, free=7 * GB, total=116 * GB, deep=False):
    return DiskReport("C", total, free, [ReportItem(label, Measured(size), kind) for label, size, kind in items], deep=deep)


def test_report_speaks_the_biggest_cleanable_caches():
    report = make_report(("cache shader NVIDIA", 9 * GB, "cache"), ("Documents", 5 * GB, "user"), ("cache npm", 2 * GB, "cache"))
    spoken, detail = report_text(report)
    assert spoken == (
        "Disk C tinggal 7 GB dari 116 GB. Yang bisa Mika bersihkan: cache shader NVIDIA 9 GB dan cache npm 2 GB, "
        "total 11 GB. Bilang hapus cache kalau mau Mika bersihkan."
    )
    assert "Documents (file kamu)" in detail and "cek detail disk" in detail


def test_report_with_small_caches_points_elsewhere():
    spoken, _ = report_text(make_report(("file sementara", 5 * 1024**2, "cache"), ("Documents", 30 * GB, "user")))
    assert "Cache-nya kecil" in spoken and "hapus cache" not in spoken


def test_deep_report_names_the_biggest_folders():
    report = make_report(("Windows", 37 * GB, "system"), ("Program Files", 10 * GB, "apps"),
                         ("cache shader NVIDIA", 9 * GB, "cache"), ("Documents", 5 * GB, "user"), deep=True)
    spoken, _ = report_text(report)
    assert "Yang paling besar: Windows 37 GB, Program Files 10 GB, dan Documents 5 GB." in spoken


@pytest.mark.parametrize(("size", "spoken"), [(9 * GB, "9 GB"), (int(1.5 * GB), "1,5 GB"), (2 * GB, "2 GB"),
                                              (160 * 1024**2, "160 MB"), (12, "kurang dari 1 MB"), (116 * GB, "116 GB")])
def test_sizes_are_rounded_for_the_voice(size, spoken):
    assert speak_size(size) == spoken


def test_cleanup_summary_mentions_skips_and_declined_admin():
    result = CleanupResult(freed=9 * GB, skipped=2, admin="declined")
    text = cleanup_summary(result, 16 * GB, "C")
    assert text == ("Beres, 9 GB lega. Disk C sekarang sisa 16 GB. 2 file dilewati karena sedang dipakai atau "
                    "dilindungi. Bagian yang butuh admin dilewati karena izinnya ditolak.")


# Deleting ----------------------------------------------------------------------------------------


def test_cleanup_empties_only_the_named_category(care, pc):
    plan = care.plan_cleanup(["nvidia"])
    assert plan.total == 5000 and plan.categories == ["nvidia"]
    assert "cache shader NVIDIA" in cleanup_question(plan)
    result = care.clean(plan)
    assert result.freed == 5000
    assert (pc.local / "NVIDIA" / "DXCache").is_dir()  # the folder stays, only its contents go
    assert list((pc.local / "NVIDIA" / "DXCache").iterdir()) == []
    assert (pc.local / "Temp" / "t.tmp").exists() and (pc.home / "Documents" / "skripsi.docx").exists()


def test_files_in_use_are_skipped_not_forced(care, pc):
    busy = pc.local / "NVIDIA" / "DXCache" / "a.bin"
    with busy.open("rb"):  # a running game holds its shader cache open
        result = care.clean(care.plan_cleanup(["nvidia"]))
    assert busy.exists() and result.skipped == 1 and result.freed == 2000


@windows_only
def test_links_inside_a_cache_are_removed_without_entering_them(care, pc):
    precious = pc.put(pc.tmp / "outside" / "keep.txt", 100)
    junction(pc.local / "Temp" / "shortcut", precious.parent)
    care.clean(care.plan_cleanup(["temp"]))
    assert precious.exists()  # the file behind the link is untouched
    assert not (pc.local / "Temp" / "shortcut").exists()  # the link itself is gone


@windows_only
def test_cache_folder_reached_through_a_link_is_refused(pc):
    elsewhere = pc.tmp / "elsewhere"
    precious = pc.put(elsewhere / "DXCache" / "photo.jpg", 100)
    nvidia = pc.local / "NVIDIA"
    for item in sorted(nvidia.rglob("*"), reverse=True):
        item.unlink() if item.is_file() else item.rmdir()
    nvidia.rmdir()
    junction(nvidia, elsewhere)  # NVIDIA now points somewhere else entirely
    with pytest.raises(UnsafeTarget):
        empty_folder(CacheFolder("nvidia", pc.local, ("NVIDIA", "DXCache")))
    assert precious.exists()


def test_admin_folders_need_one_elevation(care, pc, elevations):
    plan = care.plan_cleanup()
    assert [folder.path for folder, _ in plan.admin_items] == [pc.windows / "Temp"]
    assert "izin admin" in cleanup_question(plan)
    result = care.clean(plan)
    assert elevations == [["temp"]]
    assert result.admin == "done" and result.freed == 5000 + 500 + 1000 + 700
    assert (pc.windows / "Temp" / "w.tmp").exists()  # the fake helper deleted nothing; the real one runs as admin


def test_admin_cleanup_can_be_switched_off(care, pc, elevations):
    care.admin_cleanup = False
    plan = care.plan_cleanup()
    assert plan.admin_items == [] and "izin admin" not in cleanup_question(plan)
    care.clean(plan)
    assert elevations == []


def test_admin_helper_empties_only_admin_folders_of_named_categories(pc, monkeypatch):
    for key, value in pc.env.items():
        monkeypatch.setenv(key, value)
    report = pc.tmp / "mika-admin-clean-1.json"
    assert admin_clean_main(["--admin-clean", "temp,bogus", "--result", str(report)]) == 0
    assert json.loads(report.read_text(encoding="utf-8")) == {"freed": 700, "skipped": 0}
    assert not (pc.windows / "Temp" / "w.tmp").exists()
    assert (pc.local / "Temp" / "t.tmp").exists()  # user folders are not the helper's job


def test_admin_helper_refuses_odd_report_paths_before_deleting(pc, monkeypatch):
    for key, value in pc.env.items():
        monkeypatch.setenv(key, value)
    existing = pc.put(pc.tmp / "mika-admin-clean-2.json", 3)
    assert admin_clean_main(["--admin-clean", "temp", "--result", str(existing)]) == 2  # never overwritten
    assert admin_clean_main(["--admin-clean", "temp", "--result", str(pc.tmp / "boot.ini")]) == 2
    assert existing.read_bytes() == b"xxx" and (pc.windows / "Temp" / "w.tmp").exists()


def test_run_elevated_reads_the_helpers_report(tmp_path, monkeypatch):
    def fake_shell(program, parameters, directory, *, timeout, verb):
        assert verb == "runas" and "--admin-clean nvidia,temp" in parameters
        report = parameters.split('--result "')[1].rstrip('"')
        assert admin_clean_main(["--admin-clean", "x", "--result", report]) == 0  # writes {"freed": 0, ...}
        return "done"

    monkeypatch.setattr(disk_module, "shell_execute_and_wait", fake_shell)
    assert run_elevated(["nvidia", "temp"], tmp_path) == ("done", 0, 0)
    assert list(tmp_path.iterdir()) == []  # the report file is cleaned up

    monkeypatch.setattr(disk_module, "shell_execute_and_wait", lambda *a, **k: "declined")
    assert run_elevated(["temp"], tmp_path) == ("declined", 0, 0)


def test_helper_command_points_at_this_module():
    program, prefix, directory = disk_module._helper_command()
    assert prefix == "-m mika.skills.disk"
    assert os.path.exists(os.path.join(directory, "mika", "skills", "disk.py"))


# Routing --------------------------------------------------------------------------------------------


def route_of(config, launcher, utterance):
    return Router(config, launcher).route(clean_conversational_command(utterance))


@pytest.mark.parametrize(
    ("utterance", "intent", "args"),
    [
        ("cariin dong kenapa disk c ku penuh gitu, cari tau penyebab nya kasih tau aku", "disk_report", {"deep": False}),
        ("kenapa disk c-ku penuh", "disk_report", {"deep": False}),
        ("apa yang makan tempat di disk c", "disk_report", {"deep": False}),
        ("cek detail disk", "disk_report", {"deep": True}),
        ("hapus cache nvidia", "disk_clean", {"categories": ["nvidia"]}),
        ("hapusin cache nvidia dong", "disk_clean", {"categories": ["nvidia"]}),
        ("bersihin cache", "disk_clean", {"categories": []}),
        ("hapus file sementara", "disk_clean", {"categories": ["temp"]}),
        ("hapus shader cache", "disk_clean", {"categories": ["nvidia", "directx"]}),
        ("hapus cache chrome", "disk_clean", {"categories": [], "unsupported": "chrome"}),
    ],
)
def test_disk_routes(config, launcher, utterance, intent, args):
    route = route_of(config, launcher, utterance)
    assert (route.path, route.intent, route.args) == ("rule", intent, args)


@pytest.mark.parametrize(
    ("utterance", "intent"),
    [
        ("sisa disk berapa", "system"),  # free space only, as before
        ("hapus semua ingatan", "memory_forget_all"),
        ("hapus timer", "timer_cancel"),
        ("apa itu disk", "general"),
        ("hapus file laporan", "general"),  # no file deletion by voice
        ("kosongkan tempat sampah", "general"),  # the Recycle Bin is the user's own data
    ],
)
def test_other_hapus_and_disk_sentences_are_not_cleanup(config, launcher, utterance, intent):
    assert route_of(config, launcher, utterance).intent == intent


# End to end -------------------------------------------------------------------------------------------


class RecordingDisplay:
    def __init__(self):
        self.shown = []

    def show(self, title, body):
        self.shown.append(body)


def make(config, care, display=None):
    speaker, launcher = FakeSpeaker(), RecordingLauncher(config)
    assistant = build_assistant(config, speaker=speaker, launcher=launcher, llm=ScriptedLLM(), searcher=FakeSearcher(),
                                display=display, disk=care)
    return assistant, speaker


def test_disk_question_is_answered_without_the_llm(config, care, pc):
    pc.put(pc.local / "NVIDIA" / "DXCache" / "big.bin", 2 * 1024**2)  # the screen list hides items under 1 MB
    display = RecordingDisplay()
    assistant, speaker = make(config, care, display)
    assistant.handle("halo mika kenapa disk c ku penuh")
    assert speaker.said[0] == "Bentar, Mika cek disk dulu."
    assert speaker.said[1].startswith("Disk ") and "tinggal 7 GB dari 100 GB" in speaker.said[1]
    assert "cache shader NVIDIA" in display.shown[-1]


def test_cleanup_waits_for_yes_then_reports(config, care, pc):
    display = RecordingDisplay()
    assistant, speaker = make(config, care, display)
    assistant.handle("halo mika hapus cache nvidia")
    assert speaker.said[-1].startswith("Mika mau hapus permanen cache shader NVIDIA")
    assert "DXCache" in display.shown[-1]
    assert (pc.local / "NVIDIA" / "DXCache" / "a.bin").exists()  # nothing deleted before "iya"
    assistant.handle("iya")
    assert not (pc.local / "NVIDIA" / "DXCache" / "a.bin").exists()
    assert speaker.said[-1] == "Beres, kurang dari 1 MB lega. Disk C sekarang sisa 7 GB."


def test_cleanup_can_be_cancelled(config, care, pc):
    assistant, speaker = make(config, care)
    assistant.handle("bersihin cache")
    assistant.handle("gak jadi deh")
    assert (pc.local / "NVIDIA" / "DXCache" / "a.bin").exists() and (pc.local / "Temp" / "t.tmp").exists()


def test_unsupported_and_empty_cleanups(config, care, pc):
    assistant, speaker = make(config, care)
    assistant.handle("hapus cache chrome")
    assert "belum masuk daftar" in speaker.said[-1] and assistant.pending_action is None
    assistant.handle("hapus crash dump")  # no CrashDumps folder on this fake laptop
    assert speaker.said[-1] == "Cache-nya sudah bersih, nggak ada yang perlu dihapus."


def test_ai_gets_a_read_only_disk_tool_and_no_way_to_delete(care):
    specs = {spec.name: spec for spec in build_beyond_tools(disk=care)}
    tool = specs["disk_report"]
    assert tool.risk == "safe" and tool.relevant("kenapa disk c ku penuh")
    result = tool.handler()
    assert result.data["bisa_dibersihkan"][0]["nama"] == "cache shader NVIDIA"
    assert "AI tidak bisa menghapus" in result.data["cara_membersihkan"]
    assert not any(word in name for name in specs for word in ("hapus", "delete", "clean", "remove"))
