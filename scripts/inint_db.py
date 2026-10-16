"""兼容入口：`scripts/inint_db.py` → `scripts/init_db.py`。

文件名 "inint" 是历史拼写错误（正确是 "init"）。为了不破坏既有引用
（README / CI / Docker / 历史脚本），这里保留一个转发入口，
真正实现在 `scripts/init_db.py`。
"""

import runpy
import sys
from pathlib import Path

print(
    "[deprecated] scripts/inint_db.py 拼写有误，请改用 scripts/init_db.py"
    "（本兼容入口将在下个版本移除）",
    file=sys.stderr,
)

runpy.run_path(
    str(Path(__file__).resolve().parent / "init_db.py"),
    run_name="__main__",
)
