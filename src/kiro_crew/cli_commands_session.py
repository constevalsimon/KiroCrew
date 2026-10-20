"""The ``kirocrew session`` CLI command group.

Today one subcommand: ``repair-images``, which downscales oversized images in a
kiro-cli session transcript so the model provider's 2000px many-image cap stops
wedging the session. It is the terminal counterpart of the dashboard error
card's "Repair images and resume" action (``POST
/api/chat/slots/{slot}/repair-images``): both wire the existing
:mod:`kiro_crew.session_image_repair` module to an explicit operator action, the
distinction the module's own design note asks for.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from kiro_crew import session_image_repair
from kiro_crew.config.paths import kiro_sessions_dir


def _resolve_transcript(token: str) -> Path | None:
    """The transcript file *token* names, or None when none exists.

    *token* is either a path to a ``.jsonl``/``.json`` transcript, or a kiro-cli
    session id under :func:`kiro_sessions_dir`. A path is used verbatim; an id is
    resolved against the sessions directory, trying ``.jsonl`` then ``.json`` (the
    two spellings kiro-cli has used across versions).
    """
    as_path = Path(token)
    if as_path.suffix in (".jsonl", ".json") or as_path.exists():
        return as_path if as_path.exists() else None
    sessions_dir = kiro_sessions_dir()
    for suffix in (".jsonl", ".json"):
        candidate = sessions_dir / f"{token}{suffix}"
        if candidate.exists():
            return candidate
    return None


def _session_cmd(args: argparse.Namespace) -> None:
    """Dispatch ``kirocrew session <action>``."""
    action = getattr(args, "session_action", None)
    if action == "repair-images":
        _repair_images(args)
        return
    # No action (bare ``kirocrew session``): print usage and exit non-zero, the
    # same shape argparse gives an unknown subcommand.
    print(
        "usage: kirocrew session repair-images <session-id|path> [--apply] [--allow-live]",
        file=sys.stderr,
    )
    raise SystemExit(2)


def _repair_images(args: argparse.Namespace) -> None:
    """Resolve each session token to a transcript and run the repair over them.

    Delegates to :func:`session_image_repair.main` so the CLI and the module's
    own ``python -m`` entry point share one dry-run / apply / backup / liveness
    policy. A token that resolves to no existing transcript is reported and
    counts as a failure, rather than being silently skipped.
    """
    paths: list[str] = []
    exit_code = 0
    for token in args.session:
        resolved = _resolve_transcript(token)
        if resolved is None:
            print(
                f"{token}: no transcript found "
                f"(looked for a path, and <id>.jsonl / <id>.json under "
                f"{kiro_sessions_dir()})",
                file=sys.stderr,
            )
            exit_code = 1
            continue
        paths.append(str(resolved))
    if paths:
        argv = list(paths)
        if getattr(args, "apply", False):
            argv.append("--apply")
        if getattr(args, "allow_live", False):
            argv.append("--allow-live")
        rc = session_image_repair.main(argv)
        exit_code = exit_code or rc
    raise SystemExit(exit_code)
