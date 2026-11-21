from __future__ import annotations

import json
import re

from mika.config import DEFAULT_CONFIG, deep_merge, ensure_config, load_dotenv


def test_dotenv_parsing(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text(
        "# comment\n"
        "OPENAI_API_KEY=sk-123\n"
        'TAVILY_API_KEY="tvly abc"\n'
        "export BRAVE_API_KEY='brave'\n"
        "EMPTY=\n"
        "WITH_COMMENT=value # trailing\n"
        "not a line\n",
        encoding="utf-8",
    )
    for key in ("OPENAI_API_KEY", "TAVILY_API_KEY", "BRAVE_API_KEY", "EMPTY", "WITH_COMMENT"):
        monkeypatch.delenv(key, raising=False)
    values = load_dotenv(env)
    assert values == {
        "OPENAI_API_KEY": "sk-123",
        "TAVILY_API_KEY": "tvly abc",
        "BRAVE_API_KEY": "brave",
        "EMPTY": "",
        "WITH_COMMENT": "value",
    }


def test_real_environment_wins_over_dotenv(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("OPENAI_API_KEY=from-file\n", encoding="utf-8")
    monkeypatch.setenv("OPENAI_API_KEY", "from-shell")
    load_dotenv(env)
    import os

    assert os.environ["OPENAI_API_KEY"] == "from-shell"


def test_old_commands_json_gets_new_ai_defaults(tmp_path):
    old = {"assistant_name": "Mika", "websites": {"kampus": "https://kampus.ac.id"}, "personality": {"preset": "calm"}}
    path = tmp_path / "commands.json"
    path.write_text(json.dumps(old), encoding="utf-8")
    config = ensure_config(path)
    assert config["llm"]["ollama"]["model"] == "qwen3.5:4b"
    assert config["websites"]["kampus"] == "https://kampus.ac.id"
    assert config["websites"]["youtube"]  # defaults kept
    assert config["voice"]["edge_rate"] == "-4%"  # preset applied


def test_merged_config_does_not_alias_defaults():
    merged = deep_merge(DEFAULT_CONFIG, {})
    merged["llm"]["enabled"] = False
    merged["voice"]["enabled"] = False
    assert DEFAULT_CONFIG["llm"]["enabled"] is True
    assert DEFAULT_CONFIG["voice"]["enabled"] is True


def test_config_names_env_vars_instead_of_holding_keys():
    def walk(node, path=""):
        if isinstance(node, dict):
            for key, value in node.items():
                yield from walk(value, f"{path}.{key}")
        else:
            yield path, node

    for path, value in walk(DEFAULT_CONFIG):
        if path.endswith("api_key"):
            raise AssertionError(f"{path} would store a secret in commands.json")
        if isinstance(value, str):
            assert not re.match(r"^(sk|tvly|BSA)[-_]?[A-Za-z0-9]{12,}", value), path
    assert DEFAULT_CONFIG["llm"]["openai"]["api_key_env"] == "OPENAI_API_KEY"
