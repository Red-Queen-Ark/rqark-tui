import subprocess
import sys

PROBE = """
import sys

class Blocker:
    def find_module(self, name, path=None):
        return None

    def find_spec(self, name, path=None, target=None):
        if name in {'termios', 'fcntl', 'pwd', 'grp'}:
            raise ImportError(f'{name} is not available on this platform')
        return None

sys.meta_path.insert(0, Blocker())
import rqark_tui.tui
import rqark_tui.tui.components.main
import rqark_tui.tui.components.footer
import rqark_tui.tui.clipboard
print('imported')
"""


def test_the_package_imports_without_the_unix_only_modules() -> None:
    out = subprocess.run([sys.executable, '-c', PROBE], capture_output=True, text=True)
    assert out.stdout.strip() == 'imported', out.stderr
