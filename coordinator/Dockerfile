FROM python:3.11-slim

WORKDIR /app

# 使用国内镜像源加速（可选：注释掉恢复默认源）
RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || \
    sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list 2>/dev/null || true

# 安装 FFmpeg
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*

# 安装依赖（使用清华 pip 镜像）
COPY coordinator/requirements.txt /app/coordinator/requirements.txt
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn -r coordinator/requirements.txt

# 复制代码
COPY shared/ /app/shared/
COPY coordinator/ /app/coordinator/

# 数据目录（config.yaml 通过 volume 挂载 ./data/config.yaml）
RUN mkdir -p /app/data

EXPOSE 8787

CMD ["python", "-m", "uvicorn", "coordinator.main:app", "--host", "0.0.0.0", "--port", "8787"]
