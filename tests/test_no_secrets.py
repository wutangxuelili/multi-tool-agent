"""密钥卫生守卫：**被 Git 追踪的文件里不允许出现真实密钥**。

为什么需要：`.env` 一旦被误提交，密钥就进入历史，之后即使删除文件也仍然可被检出，
清理成本极高（要 rewrite history + 轮换所有密钥）。所以把"别提交密钥"变成机器检查。

扫描范围是 `git ls-files`（= 真正会被推送到 GitHub 的文件），因此：
- 本地 `.env`（被 .gitignore 忽略）不会导致失败——它本来就该存在；
- 占位符（`sk-xxxx…`、`your-…`、`${VAR}`）会被排除，文档示例不算泄露。

若当前目录不是 Git 仓库（例如从压缩包解压后跑测试），本测试自动跳过。
"""

import re
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent

PATTERNS = {
    "openai/兼容端点 key": re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),
    "tavily key": re.compile(r"tvly-[A-Za-z0-9_\-]{12,}"),
    "AWS access key": re.compile(r"AKIA[0-9A-Z]{16}"),
    "Google API key": re.compile(r"AIza[0-9A-Za-z_\-]{35}"),
    "GitHub token": re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}"),
    "Slack token": re.compile(r"xox[baprs]-[A-Za-z0-9\-]{10,}"),
    "私钥块": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "JWT": re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"),
}

# 文档示例 / 占位符 / 从环境读取，都不算泄露
ALLOWED = re.compile(
    r"(x{8,}|your[-_]|example|placeholder|change[-_]?me|<[^>]{1,40}>|\$\{|os\.getenv|os\.environ)",
    re.IGNORECASE,
)

MAX_FILE_BYTES = 2 * 1024 * 1024


def tracked_files() -> list[Path]:
    try:
        result = subprocess.run(
            ["git", "ls-files"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):  # pragma: no cover - 环境相关
        pytest.skip("当前目录不是 Git 仓库，跳过密钥扫描")
    return [PROJECT_ROOT / line for line in result.stdout.splitlines() if line.strip()]


@pytest.mark.parametrize("name", sorted(PATTERNS))
def test_no_real_secret_in_tracked_files(name):
    """逐个模式扫描被追踪的文件，命中真实密钥即失败（并给出文件:行号）。"""
    pattern = PATTERNS[name]
    offenders: list[str] = []

    for path in tracked_files():
        if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
            continue
        text = path.read_text("utf-8", errors="ignore")
        for match in pattern.finditer(text):
            value = match.group(0)
            if ALLOWED.search(value):
                continue
            line_no = text[: match.start()].count("\n") + 1
            masked = value[:6] + "*" * max(0, len(value) - 6)
            offenders.append(f"{path.relative_to(PROJECT_ROOT)}:{line_no} -> {masked}")

    assert not offenders, f"被追踪的文件里疑似存在{name}：{offenders}"


def test_env_file_is_never_tracked():
    """`.env` 必须保持未追踪（只有 .env.example 可以进仓库）。"""
    tracked = {p.name for p in tracked_files()}
    assert ".env" not in tracked, "本地 .env 不能被 Git 追踪，否则密钥会进历史"
    assert ".env.example" in tracked, "占位符模板 .env.example 应当保留"
