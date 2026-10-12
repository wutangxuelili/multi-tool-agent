"""pytest 全局配置。

作用：把项目根目录加入 sys.path，让 tests/ 下的测试能 import 项目模块。
"""

import sys
from pathlib import Path

# 项目根目录 = conftest.py 所在目录
PROJECT_ROOT = Path(__file__).parent

# 加入 sys.path（如果还没有）
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
