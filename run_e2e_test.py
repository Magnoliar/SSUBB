import subprocess
import time
import httpx
import sys
import os

# 1. 启动 Coordinator
print("启动 Coordinator...")
coord_proc = subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "coordinator.main:app", "--port", "8787"],
    stdout=sys.stdout,
    stderr=sys.stderr,
)

# 2. 启动 Worker
print("启动 Worker...")
worker_proc = subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "worker.main:app", "--port", "8788"],
    stdout=sys.stdout,
    stderr=sys.stderr,
)

print("等待服务启动 (10s)...")
time.sleep(10) # 给模型加载一点时间

try:
    print("发起测试任务...")
    with httpx.Client(timeout=10.0) as client:
        # 发送强制作业
        res = client.post(
            "http://127.0.0.1:8787/api/task",
            json={
                "media_path": r"C:\Users\zrhel\Desktop\浅色背景.mp4",
                "force": True,
                "target_lang": "zh"
            }
        )
        print("任务创建结果:", res.status_code, res.text)
        task_id = res.json().get("id")
        
        if not task_id:
            print("未获取到 task_id，退出")
            sys.exit(1)
            
        # 轮询状态
        print(f"开始轮询任务状态: {task_id}")
        start_t = time.time()
        while time.time() - start_t < 300: # 最大等 5 分钟
            status_res = client.get(f"http://127.0.0.1:8787/api/task/{task_id}")
            if status_res.status_code == 200:
                data = status_res.json()
                print(f"[{time.strftime('%H:%M:%S')}] 状态: {data.get('status')} | 进度: {data.get('progress')}%")
                if data.get("status") in ("completed", "failed"):
                    print("任务结束！")
                    break
            time.sleep(3)

except KeyboardInterrupt:
    print("用户中断")
except Exception as e:
    print(f"测试脚本异常: {e}")
finally:
    print("关闭服务...")
    coord_proc.terminate()
    worker_proc.terminate()
    coord_proc.wait()
    worker_proc.wait()
    print("测试完毕。请检查 C:\\Users\\zrhel\\Desktop 是否有生成的字幕文件。")
