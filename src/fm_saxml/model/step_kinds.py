"""Script step names by role: block structure (for indentation and folding) and the
control steps FileMaker's Script Workspace colours.

The one source for these sets: step_text.py indents with them and the HTML viewer gets
them through its manifest (``stepKinds``).
"""

from __future__ import annotations

# Steps that open, continue or close a block.
OPENS = frozenset({"If", "Loop", "Open Transaction"})
CONTINUES = frozenset({"Else", "Else If"})
CLOSES = frozenset({"End If", "End Loop", "Commit Transaction"})

# Control steps the Script Workspace shows in a different colour.
COLOURED = frozenset({
    "Allow User Abort",
    "Commit Transaction",
    "Else",
    "Else If",
    "End If",
    "End Loop",
    "Exit Loop If",
    "Exit Script",
    "Halt Script",
    "If",
    "Loop",
    "Open Transaction",
    "Pause/Resume Script",
    "Perform Script",
    "Perform Script on Server",
    "Perform Script on Server with Callback",
    "Revert Transaction",
    "Set Error Capture",
    "Set Revert Transaction on Error",
})
