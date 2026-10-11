"""Errors the AI can act on. Each one says what happened and what to do next."""

from __future__ import annotations

import json
from typing import Any

# Codes documented by the Archicad JSON API and observed on Archicad 29.
BUSY_CODE = 4001  # "Invalid program status (ongoing user input)"
NOT_REGISTERED_CODE = 4010  # add-on command not registered in this instance


class ArchicadError(Exception):
    """Base class. `code` is the Archicad error code when there is one."""

    def __init__(self, message: str, code: int | None = None, detail: Any = None):
        super().__init__(message)
        self.code = code
        self.detail = detail


class ArchicadUnavailable(ArchicadError):
    """Nothing answered on the port, or the answer was not valid JSON."""


class ArchicadBusy(ArchicadError):
    """Archicad refused the call because it is in a user interaction state.

    This is not proof that a dialog is open, and it says nothing about whether
    an add-on is loaded. Retry after the user finishes the current action.
    """


class CommandNotRegistered(ArchicadError):
    """The command is not available in this instance (usually Tapir not loaded)."""


class CommandFailed(ArchicadError):
    """Archicad answered with an error for this command."""


class TapirError(ArchicadError):
    """Tapir answered, but reported an error or an unexpected response."""


class NoInstance(ArchicadError):
    """No Archicad instance is reachable."""


class AmbiguousTarget(ArchicadError):
    """Several instances are open and the call did not say which one to use."""


def from_api_error(error: Any) -> ArchicadError:
    """Map an Archicad `error` object to the matching exception."""
    code = error.get("code") if isinstance(error, dict) else None
    text = error.get("message") if isinstance(error, dict) else None
    raw = json.dumps(error, ensure_ascii=False)
    if code == BUSY_CODE:
        return ArchicadBusy(
            "Archicad is busy with user input. Ask the user to finish the current action, "
            "then retry. This does not mean an add-on is missing.",
            code,
            error,
        )
    if code == NOT_REGISTERED_CODE:
        return CommandNotRegistered(
            "Command not registered in this Archicad instance. If it is a Tapir command, "
            "check that the Tapir add-on is loaded (tapir_status).",
            code,
            error,
        )
    return CommandFailed(f"Archicad error: {text or raw}", code, error)
