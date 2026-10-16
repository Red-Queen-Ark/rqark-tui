"""System clipboard helpers.

Textual's ``App.copy_to_clipboard`` only stores a *local*, in-app clipboard
(used by ``Input``/``TextArea`` for Ctrl+V inside the app). For "normal"
copy-paste — i.e. pasting into other applications — the text must also be
pushed to the OS clipboard via the platform's CLI tool.
"""

import shutil
import subprocess
import sys


def write_system_clipboard(text: str) -> None:
    """Write ``text`` to the OS clipboard.

    Uses ``pbcopy`` on macOS, ``clip`` on Windows, and ``xclip``/``xsel`` on
    Linux. Failures are silently ignored (clipboard access is best-effort).
    """
    if sys.platform == 'darwin':
        command = ['pbcopy']
    elif sys.platform.startswith('win'):
        command = ['clip']
    else:
        command = None
        for candidate in (['xclip', '-selection', 'clipboard'], ['xsel', '--clipboard', '--input']):
            if shutil.which(candidate[0]):
                command = candidate
                break
    if command is None:
        return
    try:
        subprocess.run(command, input=text.encode('utf-8'), check=True)
    except OSError, subprocess.SubprocessError:
        pass
