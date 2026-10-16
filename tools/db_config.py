"""数据库位置配置（集中一处，便于被测试替换）。

路径规则（含环境变量覆盖）统一在 `utils/paths.py`，这里只是把它
重导出成 `DB_PATH`，让 `tools/database.py` 与 `tools/database_admin.py`
在**调用时**读取同一个值；测试只要 monkeypatch 本模块的 `DB_PATH`
就能把两个工具一起指向临时库。
"""

from utils.paths import COMPANY_DB as DB_PATH

__all__ = ["DB_PATH"]
