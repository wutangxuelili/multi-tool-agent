"""file_server 路径白名单的回归测试。

这些用例对应一次真实的越权漏洞：旧实现用
`full_path.startswith(ALLOWED_DIR)` 做字符串前缀匹配，
导致与 `documents/` 共享前缀的兄弟目录（`documents_evil/`）可以读取。
"""

import os

import pytest

from mcp_servers import file_server


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """把白名单根目录指到临时沙箱，便于自由构造越界场景。"""
    allowed = tmp_path / "documents"
    allowed.mkdir()
    (allowed / "inside.txt").write_text("INSIDE-OK", encoding="utf-8")
    (allowed / "sub").mkdir()
    (allowed / "sub" / "nested.txt").write_text("NESTED-OK", encoding="utf-8")

    evil = tmp_path / "documents_evil"
    evil.mkdir()
    (evil / "secret.txt").write_text("LEAKED-SECRET", encoding="utf-8")

    (tmp_path / "outside.txt").write_text("OUTSIDE-SECRET", encoding="utf-8")

    monkeypatch.setattr(file_server, "ALLOWED_DIR", allowed.resolve())
    return tmp_path


def test_reads_file_inside_whitelist(sandbox):
    assert file_server.read_file("inside.txt") == "INSIDE-OK"


def test_reads_nested_file_inside_whitelist(sandbox):
    assert file_server.read_file("sub/nested.txt") == "NESTED-OK"


@pytest.mark.parametrize(
    "path",
    [
        "../documents_evil/secret.txt",  # 共享前缀的兄弟目录（旧实现的漏网之鱼）
        "..\\documents_evil\\secret.txt",  # 同上，Windows 分隔符
        "../outside.txt",  # 纯上级目录
        "..",
        "../",
        "sub/../../documents_evil/secret.txt",  # 绕一圈再出去
    ],
)
def test_blocks_traversal_outside_whitelist(sandbox, path):
    result = file_server.read_file(path)
    assert "不允许访问" in result, f"{path} 不应被放行，实际返回：{result}"
    assert "SECRET" not in result


def test_blocks_absolute_path(sandbox):
    target = sandbox / "outside.txt"
    result = file_server.read_file(str(target))
    assert "不允许访问" in result


def test_blocks_symlink_escape(sandbox):
    """白名单目录内的符号链接指向目录外时也必须拒绝。"""
    link = sandbox / "documents" / "link.txt"
    try:
        os.symlink(sandbox / "outside.txt", link)
    except (OSError, NotImplementedError):
        pytest.skip("当前环境不允许创建符号链接（Windows 需要开发者模式/管理员）")

    result = file_server.read_file("link.txt")
    assert "不允许访问" in result
    assert "OUTSIDE-SECRET" not in result


def test_missing_file_reports_not_exists(sandbox):
    result = file_server.read_file("not_exist.txt")
    assert "文件不存在" in result


def test_truncates_long_file(sandbox):
    long_text = "x" * (file_server.MAX_LEN + 100)
    (sandbox / "documents" / "long.txt").write_text(long_text, encoding="utf-8")

    result = file_server.read_file("long.txt")
    assert "已截断" in result
    assert len(result) < len(long_text)


def test_whitelist_does_not_depend_on_cwd(tmp_path, monkeypatch):
    """白名单基于 __file__，换工作目录也必须能读到仓库自带的 documents/。"""
    monkeypatch.chdir(tmp_path)
    assert file_server.read_file("test.txt").strip() == "Hello from MCP!"
