"""``kirocrew session repair-images``: the terminal half of #14718's recovery.

The dashboard error card's Repair action and this command both wire the existing
``session_image_repair`` module to an explicit operator action. These tests pin
the CLI-specific glue: resolving a session id (or a path) to a transcript file,
the dry-run / ``--apply`` split, and reporting a missing session as a failure
rather than silently skipping it. The repair arithmetic itself is covered by
``test_session_image_repair``.
"""

from __future__ import annotations

import argparse
import io
import json
from pathlib import Path

import pytest

from kiro_crew.cli_commands_session import _session_cmd
from kiro_crew.config import paths as cfg_paths


@pytest.fixture
def sessions_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An isolated kiro-cli sessions directory, via the module's own override
    lever (``_sessions_dir_override``) -- the only hook that reaches a lazily
    resolved path. Removed by monkeypatch at teardown, so nothing touches the
    operator's real ``~/.kiro/sessions/cli``."""
    d = tmp_path / "sessions" / "cli"
    d.mkdir(parents=True)
    monkeypatch.setattr(cfg_paths, "_sessions_dir_override", lambda: d)
    return d


def _oversized_transcript(path: Path) -> None:
    """Write a transcript holding one 3000x10 PNG, in kiro-cli's real block
    shape (``data.content[i]`` with a ``bytes`` source as a list of ints)."""
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (3000, 10), (10, 20, 30)).save(buf, format="PNG")
    payload = list(buf.getvalue())
    record = {
        "data": {
            "content": [
                {"kind": "text", "text": "hi"},
                {
                    "kind": "image",
                    "data": {"format": "png", "source": {"kind": "bytes", "data": payload}},
                },
            ]
        }
    }
    path.write_text(json.dumps(record) + "\n")


def _run(session: list[str], *, apply: bool = False, allow_live: bool = False) -> int:
    ns = argparse.Namespace(
        session_action="repair-images",
        session=session,
        apply=apply,
        allow_live=allow_live,
    )
    with pytest.raises(SystemExit) as exc:
        _session_cmd(ns)
    assert isinstance(exc.value.code, int)
    return exc.value.code


def _longest_edge(path: Path) -> int:
    from PIL import Image

    record = json.loads(path.read_text().splitlines()[0])
    block = record["data"]["content"][1]
    data = bytes(block["data"]["source"]["data"])
    with Image.open(io.BytesIO(data)) as im:
        return max(im.size)


def test_dry_run_reports_and_changes_nothing(sessions_dir: Path) -> None:
    t = sessions_dir / "abc123.jsonl"
    _oversized_transcript(t)
    before = t.read_bytes()
    # Resolve by bare session id -- the CLI maps it to <id>.jsonl under the dir.
    assert _run(["abc123"]) == 0
    assert t.read_bytes() == before
    assert not (sessions_dir / "abc123.jsonl.pre-image-repair.bak").exists()


def test_apply_downscales_and_backs_up(sessions_dir: Path) -> None:
    t = sessions_dir / "abc123.jsonl"
    _oversized_transcript(t)
    assert _longest_edge(t) == 3000
    assert _run(["abc123"], apply=True) == 0
    assert _longest_edge(t) <= 2000
    assert (sessions_dir / "abc123.jsonl.pre-image-repair.bak").exists()


def test_a_path_is_accepted_verbatim(sessions_dir: Path, tmp_path: Path) -> None:
    t = tmp_path / "loose.jsonl"
    _oversized_transcript(t)
    assert _run([str(t)], apply=True) == 0
    assert _longest_edge(t) <= 2000


def test_a_missing_session_is_a_failure_not_a_silent_skip(sessions_dir: Path) -> None:
    assert _run(["no-such-session"]) == 1


def test_no_action_prints_usage_and_exits_nonzero() -> None:
    ns = argparse.Namespace(session_action=None)
    with pytest.raises(SystemExit) as exc:
        _session_cmd(ns)
    assert exc.value.code == 2
