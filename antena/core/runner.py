"""Ejecución de comandos externos sin shell y con tiempos límite."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from typing import Mapping, Protocol, Sequence


@dataclass(frozen=True)
class CommandResult:
    args: tuple[str, ...]
    returncode: int
    stdout: str = ""
    stderr: str = ""

    @property
    def ok(self) -> bool:
        return self.returncode == 0


class Runner(Protocol):
    def run(
        self,
        args: Sequence[str],
        timeout: float = 15.0,
        env: Mapping[str, str] | None = None,
    ) -> CommandResult: ...

    def which(self, program: str) -> str | None: ...


class CommandRunner:
    """Runner real. Nunca usa shell=True ni interpola texto en una cadena."""

    def run(
        self,
        args: Sequence[str],
        timeout: float = 15.0,
        env: Mapping[str, str] | None = None,
    ) -> CommandResult:
        argv = tuple(str(item) for item in args)
        if not argv:
            raise ValueError("argv vacío")
        try:
            completed = subprocess.run(
                list(argv),
                shell=False,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=dict(env) if env is not None else None,
                check=False,
            )
        except FileNotFoundError:
            return CommandResult(argv, 127, "", f"no encontrado: {argv[0]}")
        except subprocess.TimeoutExpired:
            return CommandResult(argv, 124, "", f"tiempo agotado: {' '.join(argv)}")
        except OSError as exc:
            return CommandResult(argv, 126, "", str(exc))
        return CommandResult(argv, completed.returncode, completed.stdout, completed.stderr)

    def which(self, program: str) -> str | None:
        return shutil.which(program)
