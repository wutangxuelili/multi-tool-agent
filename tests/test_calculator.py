"""计算器工具的单元测试。"""

from tools.calculator import calculate


def test_basic_addition():
    assert calculate.invoke({"expression": "1 + 2"}) == "3"


def test_operator_precedence():
    assert calculate.invoke({"expression": "(25 + 17) * 3"}) == "126"


def test_power_operation():
    assert calculate.invoke({"expression": "2 ** 10"}) == "1024"


def test_division_by_zero_returns_error():
    """除零应返回错误字符串，而不是抛异常。"""
    result = calculate.invoke({"expression": "10 / 0"})
    assert "错误" in result or "失败" in result or "zero" in result.lower()
