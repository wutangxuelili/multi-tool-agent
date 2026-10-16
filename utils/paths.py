"""运行时路径的集中配置。

为什么要有这个模块：早期版本把 `data/company.db`、`logs/`、`documents/`、
`checkpoints.db` 全部写成**相对当前工作目录**的路径，换个目录运行就失效，
README 只好用"请始终在项目根目录运行"来兜底。现在所有路径都以
**仓库根目录（本文件的上上级）**为基准，并支持环境变量覆盖，便于容器/测试/部署。

覆盖用的环境变量：
    DATA_DIR              数据目录（默认 <repo>/data）
    LOGS_DIR              日志目录（默认 <repo>/logs）
    DOCUMENTS_DIR         MCP 可读白名单目录（默认 <repo>/documents）
    COMPANY_DB_PATH       公司员工库（默认 <DATA_DIR>/company.db）
    CHECKPOINT_DB         LangGraph 状态快照（默认 <repo>/checkpoints.db）
    SENSITIVE_AUDIT_LOG   敏感操作审计（默认 <LOGS_DIR>/sensitive_ops.jsonl）
"""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _env_path(name: str, default: Path) -> Path:
    value = os.getenv(name)
    return Path(value) if value else default


DATA_DIR = _env_path("DATA_DIR", PROJECT_ROOT / "data")
LOGS_DIR = _env_path("LOGS_DIR", PROJECT_ROOT / "logs")
DOCUMENTS_DIR = _env_path("DOCUMENTS_DIR", PROJECT_ROOT / "documents")

COMPANY_DB = _env_path("COMPANY_DB_PATH", DATA_DIR / "company.db")
CHECKPOINTS_DB = _env_path("CHECKPOINT_DB", PROJECT_ROOT / "checkpoints.db")
AUDIT_LOG = _env_path("SENSITIVE_AUDIT_LOG", LOGS_DIR / "sensitive_ops.jsonl")
AGENT_LOG = LOGS_DIR / "agent.log"
