# Dockerfile
# 使用官方Python运行时作为基础镜像
FROM python:3.12-slim-bookworm

# 设置时区，确保容器内的时间与宿主机一致或符合预期
ENV TZ=Asia/Shanghai

# 设置工作目录
WORKDIR /app

# 复制项目的依赖文件到容器中
COPY requirements.txt .

# 安装Python依赖
RUN pip install --no-cache-dir -r requirements.txt

# 复制所有项目文件到容器中
# 确保你的主应用文件（例如 main.py）也在复制范围内
COPY . .

# 设置 PYTHONPATH，确保Python能找到 /app 目录下的模块
ENV PYTHONPATH=/app

# 定义容器启动时执行的命令
# 假设你的Bot入口文件是 main.py
CMD ["python", "main.py"]