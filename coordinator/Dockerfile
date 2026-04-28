FROM python:3.11-slim

WORKDIR /app

# 安装 FFmpeg
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

# 安装依赖
COPY coordinator/requirements.txt /app/coordinator/requirements.txt
RUN pip install --no-cache-dir -r coordinator/requirements.txt

# 复制代码
COPY shared/ /app/shared/
COPY coordinator/ /app/coordinator/
COPY config.yaml /app/config.yaml

# 数据目录
RUN mkdir -p /app/data

EXPOSE 8787

CMD ["python", "-m", "uvicorn", "coordinator.main:app", "--host", "0.0.0.0", "--port", "8787"]
