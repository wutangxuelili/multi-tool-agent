FROM python:3.11-slim

# 不写 .pyc、日志不缓冲（容器里能实时看到输出）
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

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

# 以非 root 运行（安全基线）；运行时目录归 appuser，compose 里用命名卷挂载
RUN useradd --create-home --shell /usr/sbin/nologin appuser \
    && mkdir -p /app/logs /app/data \
    && chown -R appuser:appuser /app
USER appuser

# 说明：本镜像同时承载"内部 API"和"Agent"两个角色，健康检查在
# docker-compose.yml 上按服务声明（只对 internal-api 有意义），因此这里不加
# HEALTHCHECK，也不写 EXPOSE（端口映射由 compose 声明）。

CMD ["python", "main.py"]
