"""Cliente del componente privilegiado, invocado mediante pkexec."""

from __future__ import annotations

import json
import selectors
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event
from typing import Any, Callable

from antena.constants import helper_path


@dataclass
class PrivilegedResult:
    ok: bool = False
    code: str = ""
    message: str = ""
    technical: str = ""
    cancelled: bool = False
    data: dict[str, Any] = field(default_factory=dict)


class PrivilegedClient:
    def __init__(
        self,
        helper: Path | None = None,
        pkexec: str | None = None,
        timeout: float = 1900.0,
    ) -> None:
        self.helper = helper if helper is not None else helper_path()
        if pkexec:
            self.pkexec = pkexec
        elif Path("/usr/bin/pkexec").is_file():
            self.pkexec = "/usr/bin/pkexec"
        else:
            self.pkexec = shutil.which("pkexec")
        self.timeout = timeout

    @property
    def available(self) -> bool:
        return bool(self.helper and Path(self.helper).is_file() and self.pkexec)

    def call(
        self,
        operation: str,
        payload: dict[str, Any],
        on_progress: Callable[[str, str], None] | None = None,
        cancel: Event | None = None,
    ) -> PrivilegedResult:
        if not self.available:
            return PrivilegedResult(
                ok=False,
                code="helper_missing",
                message="Falta el componente privilegiado de Antena.",
            )
        if not isinstance(operation, str) or not operation.isidentifier():
            return PrivilegedResult(ok=False, code="bad_operation", message="Operación no válida.")
        argv = [str(self.pkexec), str(self.helper), operation]
        try:
            process = subprocess.Popen(
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                shell=False,
                bufsize=1,
            )
        except OSError as exc:
            return PrivilegedResult(ok=False, code="spawn_failed", message=str(exc))
        assert process.stdin is not None
        assert process.stdout is not None
        assert process.stderr is not None
        try:
            process.stdin.write(json.dumps(payload))
            process.stdin.close()
        except OSError:
            pass

        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        final: dict[str, Any] | None = None
        deadline = time.monotonic() + self.timeout
        try:
            while True:
                if cancel is not None and cancel.is_set():
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                    return PrivilegedResult(ok=False, code="cancelled", message="Cancelado.", cancelled=True)
                if time.monotonic() > deadline:
                    process.kill()
                    return PrivilegedResult(ok=False, code="timeout", message="La operación tardó demasiado.")
                events = selector.select(timeout=0.2)
                if not events:
                    if process.poll() is not None:
                        break
                    continue
                line = process.stdout.readline()
                if not line:
                    break
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(event, dict):
                    continue
                if event.get("event") == "progress":
                    if on_progress:
                        on_progress(str(event.get("message", "")), str(event.get("technical", "")))
                elif event.get("event") == "result":
                    final = event
        finally:
            selector.close()
        try:
            stderr = process.stderr.read()
            process.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            stderr = ""
        if final is None:
            code = "auth_cancelled" if process.returncode in (126, 127) else "no_result"
            message = (
                "Autorización cancelada."
                if code == "auth_cancelled"
                else "El componente privilegiado no devolvió un resultado."
            )
            return PrivilegedResult(
                ok=False,
                code=code,
                message=message,
                technical=(stderr or "").strip()[-1000:],
                cancelled=code == "auth_cancelled",
            )
        data = {key: value for key, value in final.items() if key not in {"event", "ok", "message", "technical", "code"}}
        return PrivilegedResult(
            ok=bool(final.get("ok")),
            code=str(final.get("code", "")),
            message=str(final.get("message", "")),
            technical=str(final.get("technical", "")),
            cancelled=str(final.get("code", "")) == "cancelled",
            data=data,
        )
