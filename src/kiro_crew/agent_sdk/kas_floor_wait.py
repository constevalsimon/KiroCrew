"""The wait a spawn takes for the kiro-cli floor's verdict on a defaulted KAS.

With no ``agent.acp_backend`` stored, the main backend resolves to KAS; with no
``agent.member_acp_backend`` stored, crew-member DMs do. The gateway checks whether
this kiro-cli can serve KAS (``apply_kas_cli_floor``) in the background, so boot
never waits on its ``acp --help`` probe. A spawn that ran before that verdict landed
would start KAS on a kiro-cli that rejects ``--agent-engine``, and the user's first
turn would fail. So the gateway arms this gate with the floor's task for each role
(main, member) whose KAS was DEFAULTED, and each async spawn path awaits
:func:`await_kas_floor_verdict` for its role before it calls the provider factory.
The factory then reads whatever the verdict decided.

An explicit KAS choice is never armed: that user asked for KAS and keeps the old
behavior. The wait is bounded by the probe's own timeout, counted from when the gate
was armed, so a hung check costs at most one probe's worth of delay in total. After
the deadline, or when the spawn's role is not armed, the spawn goes ahead at once.
"""

from __future__ import annotations

import asyncio
from typing import Any

from kiro_crew.kiro_cli import _KAS_HELP_PROBE_TIMEOUT_SECS

#: The longest a spawn waits for the verdict, measured from the arm time.
KAS_FLOOR_WAIT_SECS: float = float(_KAS_HELP_PROBE_TIMEOUT_SECS)

#: The armed verdict, its loop-time deadline and whether main / member spawns wait.
_armed: tuple[asyncio.Future[Any], float, bool, bool] | None = None


def arm_kas_floor_wait(verdict: asyncio.Future[Any], *, main: bool, member: bool) -> None:
    """Make *main* and/or *member* spawns wait for *verdict*. Call it on the loop."""
    global _armed
    if not (main or member):
        _armed = None
        return
    deadline = asyncio.get_running_loop().time() + KAS_FLOOR_WAIT_SECS
    _armed = (verdict, deadline, main, member)


def disarm_kas_floor_wait() -> None:
    """Drop any armed verdict, so no spawn waits."""
    global _armed
    _armed = None


async def await_kas_floor_verdict(*, member: bool = False) -> None:
    """Wait, bounded, for an armed floor verdict that has not landed yet.

    *member* says the spawn is a crew-member DM, which runs ``member_acp_backend``.
    Returns at once when that role is not armed or the verdict already landed.
    Never raises for the verdict: a failed or timed-out check leaves the backend as
    configured, which is what the floor itself does on an unknown answer.
    """
    armed = _armed
    if armed is None:
        return
    verdict, deadline, main_armed, member_armed = armed
    if not (member_armed if member else main_armed):
        return
    loop = asyncio.get_running_loop()
    # A verdict armed on another loop (an earlier gateway in the same process)
    # cannot be awaited here, and was never this spawn's to wait for.
    if verdict.done() or verdict.get_loop() is not loop:
        return
    remaining = deadline - loop.time()
    if remaining <= 0:
        return
    # ``asyncio.wait`` neither cancels the verdict on timeout nor raises its
    # exception, so one waiter giving up never touches the floor's own task.
    await asyncio.wait({verdict}, timeout=remaining)
