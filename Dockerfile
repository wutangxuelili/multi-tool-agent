FROM python:3.11-slim

WORKDIR /app

# 装依赖（单独一层，利用缓存）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制代码
COPY agent/ ./agent/
COPY tools/ ./tools/
COPY mcp_servers/ ./mcp_servers/
COPY internal_api/ ./internal_api/
COPY utils/ ./utils/
COPY scripts/ ./scripts/
COPY documents/ ./documents/
COPY llm_client.py .
COPY main.py .

# 创建运行时目录
RUN mkdir -p logs data

EXPOSE 8001

CMD ["python", "main.py"]