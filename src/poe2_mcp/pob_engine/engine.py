"""
Client for the headless Path of Building daemon (lua/pob_driver.lua).

Manages a single long-lived LuaJIT process so the ~1s PoB init is paid once, then
exchanges line-delimited JSON over stdio (see docs/p3-headless-pob.md). Requests are
serialized under a lock; a stderr-suppressed reader thread feeds responses to a queue
so reads can time out without blocking forever. On timeout or crash the process is
torn down and respawned on the next call.

The engine is optional: if PoB is not set up (scripts/setup_pob.py), available()
returns False and callers should degrade gracefully rather than error.
"""

from __future__ import annotations

import atexit
import json
import os
import queue
import shutil
import subprocess
import threading
from pathlib import Path

from .._resources import resource_path
from .setup import DEFAULT_PATH, DEFAULT_REF, SetupError, ensure_pob, is_set_up

_DRIVER = resource_path("lua", "pob_driver.lua")


class PobEngineError(RuntimeError):
    """Raised when the headless engine is unavailable or a request fails."""


class PobEngine:
    def __init__(self, root: str | Path | None = None, cmd: str | None = None,
                 timeout_ms: int | None = None, driver: str | Path | None = None,
                 ref: str | None = None, autosetup: bool | None = None):
        self.root = Path(root or os.environ.get("POB_FORK_PATH") or DEFAULT_PATH)
        self.cmd = cmd or os.environ.get("POB_CMD") or "luajit"
        self.timeout = (timeout_ms or int(os.environ.get("POB_TIMEOUT_MS", "10000"))) / 1000
        self.driver = Path(driver or os.environ.get("POB_DRIVER") or _DRIVER)
        self.ref = ref or os.environ.get("POB_REF") or DEFAULT_REF
        # Fetch PoB automatically on first use (the clone is small/fast now). Opt out
        # with POB_AUTOSETUP=0 or autosetup=False.
        self.autosetup = (os.environ.get("POB_AUTOSETUP", "1") != "0") if autosetup is None else autosetup
        self._proc: subprocess.Popen | None = None
        self._q: queue.Queue[str | None] = queue.Queue()
        # Re-entrant: recompute/skill_groups hold it across their whole multi-request
        # sequence (load → select → set_config → get_output) — the daemon is stateful,
        # so interleaving two sequences would compute stats under the wrong config.
        self._lock = threading.RLock()
        self._id = 0
        self._cache: dict[tuple, dict] = {}      # (xml, overrides, stats, group) -> output
        self._versions: dict[int, dict] = {}     # hash(xml) -> {tree_version, pob_tree_version}
        self._skills: dict[int, list] = {}       # hash(xml) -> socket-group list
        atexit.register(self.close)

    # -- lifecycle ---------------------------------------------------------

    def available(self) -> bool:
        """True if recompute can run now or be made to run: the Lua interpreter is on
        PATH and the driver exists, and PoB is either set up or can be auto-fetched."""
        return (
            shutil.which(self.cmd) is not None
            and self.driver.exists()
            and (is_set_up(self.root) or self.autosetup)
        )

    def _start(self) -> None:
        if self._proc and self._proc.poll() is None:
            return
        if shutil.which(self.cmd) is None:
            raise PobEngineError(
                f"'{self.cmd}' not found on PATH — install LuaJIT to enable DPS recompute "
                "(e.g. `sudo dnf install luajit`, `brew install luajit`, `apt install luajit`)."
            )
        if not self.driver.exists():
            raise PobEngineError(f"PoB driver not found at {self.driver}.")
        if not is_set_up(self.root):
            if not self.autosetup:
                raise PobEngineError(
                    f"Headless PoB not set up in {self.root}. Run "
                    "`uv run python scripts/setup_pob.py`, or set POB_AUTOSETUP=1."
                )
            try:
                ensure_pob(self.root, ref=self.ref, cmd=self.cmd)  # slim ~50MB fetch, one-time
            except SetupError as e:
                raise PobEngineError(f"automatic PoB setup failed: {e}") from e
        self._proc = subprocess.Popen(
            [self.cmd, str(self.driver), str(self.root)],
            cwd=self.root / "src",
            env={**os.environ, "CI": "true"},  # CI=true skips the slow ModCache path
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
        self._q = queue.Queue()
        self._id = 0
        threading.Thread(target=self._reader, args=(self._proc.stdout,), daemon=True).start()

    def _reader(self, stdout) -> None:
        for line in stdout:
            line = line.strip()
            if line:
                self._q.put(line)
        self._q.put(None)  # EOF sentinel — process exited

    def _restart(self) -> None:
        self.close()
        self._proc = None

    def close(self) -> None:
        proc, self._proc = self._proc, None
        if proc and proc.poll() is None:
            try:
                proc.stdin.write('{"cmd":"shutdown"}\n')
                proc.stdin.flush()
                proc.wait(timeout=2)
            except Exception:
                pass
            if proc.poll() is None:
                proc.kill()

    # -- request/response --------------------------------------------------

    def _request(self, **req) -> dict:
        with self._lock:
            self._start()
            self._id += 1
            req["id"] = self._id
            try:
                self._proc.stdin.write(json.dumps(req) + "\n")
                self._proc.stdin.flush()
            except (BrokenPipeError, ValueError):
                self._restart()
                raise PobEngineError("engine process is not writable (restarted)")
            try:
                line = self._q.get(timeout=self.timeout)
            except queue.Empty:
                self._restart()
                raise PobEngineError(f"engine timed out after {self.timeout:g}s (restarted)")
            if line is None:
                self._restart()
                raise PobEngineError("engine process exited unexpectedly (restarted)")
            resp = json.loads(line)
            if not resp.get("ok"):
                raise PobEngineError(resp.get("error", "unknown engine error"))
            return resp

    # -- high-level API ----------------------------------------------------

    def ping(self) -> bool:
        return bool(self._request(cmd="ping").get("pong"))

    def load(self, xml: str) -> dict:
        resp = self._request(cmd="load", xml=xml)
        self._versions[hash(xml)] = {
            "tree_version": resp.get("tree_version"),
            "pob_tree_version": resp.get("pob_tree_version"),
        }
        return resp

    def set_config(self, overrides: dict) -> None:
        self._request(cmd="set_config", overrides=overrides)

    def get_output(self, stats: list[str] | None = None) -> dict:
        return self._request(cmd="get_output", stats=stats).get("output", {})

    def recompute(self, xml: str, overrides: dict | None = None,
                  stats: list[str] | None = None, skill_group: int | None = None) -> dict:
        """Load a build, optionally select a skill group and apply config overrides,
        then return the requested computed stats. Results are cached per
        (build, overrides, stats, skill_group) — identical calls skip the round-trip."""
        # Overrides come from tool input and may hold nested values; json.dumps
        # keys them without the TypeError tuple(sorted(...)) hits on unhashables.
        key = (
            hash(xml),
            json.dumps(overrides or {}, sort_keys=True, default=str),
            tuple(stats or ()),
            skill_group,
        )
        if key in self._cache:
            return self._cache[key]

        with self._lock:  # the whole sequence — the daemon is stateful
            self.load(xml)
            if skill_group is not None:
                self._request(cmd="select_skill", group=skill_group)
            if overrides:
                self.set_config(overrides)
            out = self.get_output(stats)

        self._cache[key] = out
        if len(self._cache) > 64:                 # simple bound, FIFO eviction
            self._cache.pop(next(iter(self._cache)))
        return out

    def skill_groups(self, xml: str) -> list[dict]:
        """Return the build's socket groups as PoB indexes them: each has index
        (1-based, for skill_group / select_skill), skill (active skill name), label,
        enabled, is_main. Cached per build."""
        h = hash(xml)
        if h not in self._skills:
            with self._lock:  # load + list as one unit — the daemon is stateful
                self.load(xml)
                self._skills[h] = self._request(cmd="list_skills").get("skills", [])
        return self._skills[h]

    def version_note(self, xml: str) -> str | None:
        """A caveat string if the build's tree version differs from PoB's bundled
        data (some passives may not map), else None."""
        v = self._versions.get(hash(xml)) or {}
        bt, pt = v.get("tree_version"), v.get("pob_tree_version")
        if bt and pt and str(bt) != str(pt):
            return (
                f"Build tree version {bt} differs from the bundled PoB data ({pt}); "
                "some passives may not map and the result can be approximate. "
                "Pin POB_REF to a PoB release matching the league to align them."
            )
        return None


_engine: PobEngine | None = None


def get_engine() -> PobEngine:
    """Return a process-wide PobEngine singleton (lazily constructed)."""
    global _engine
    if _engine is None:
        _engine = PobEngine()
    return _engine
