import time
from rqark_tui.libs.tui.draw import TerminalDraw

t = TerminalDraw()
t.clear()
t.update()
time.sleep(2)
t.restore()