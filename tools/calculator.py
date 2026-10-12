from langchain_core.tools import tool
from pydantic import BaseModel, Field
from simpleeval import simple_eval


class CalculatorArgs(BaseModel):
    expression: str = Field(min_length=1, description="数学表达式，例如：1 + 2 * 3")


@tool(args_schema=CalculatorArgs)
def calculate(expression: str) -> str:
    """计算数学表达式，支持加减乘除、幂运算和括号。"""
    try:
        result = simple_eval(expression)
        return str(result)
    except Exception as e:  # noqa: BLE001
        return f"计算失败：{e}"


if __name__ == "__main__":
    print("name", calculate.name)
    print("description", calculate.description)
    print("args_schema", calculate.args_schema.model_json_schema())
    print(calculate.invoke({"expression": "1+2"}))
    print(calculate.invoke({"expression": "(10+5)*3"}))
    print(calculate.invoke({"expression": "10 / 0"}))
