#!/bin/bash

# 启动前后端服务的脚本
# 使用 nohup 让服务在后台运行,不受终端关闭影响

set -e

PROJECT_DIR="/root/usr/skill_agent_demo"
BACKEND_DIR="$PROJECT_DIR/backend"
FRONTEND_DIR="$PROJECT_DIR/frontend"

echo "=========================================="
echo "启动 Skill Agent Demo 服务"
echo "=========================================="

# 检查并创建日志目录
mkdir -p "$PROJECT_DIR/logs"

# 1. 启动后端服务
echo ""
echo "[1/2] 启动后端服务..."
cd "$BACKEND_DIR"

# 检查虚拟环境
if [ ! -d "venv" ]; then
    echo "创建 Python 虚拟环境..."
    python3 -m venv venv
fi

# 激活虚拟环境并安装依赖
source venv/bin/activate
echo "安装后端依赖..."
pip install -q -r requirements.txt

# 检查 .env 文件
if [ ! -f ".env" ]; then
    echo "警告: 未找到 .env 文件"
    echo "请创建 backend/.env 文件并配置 GEMINI_API_KEY"
    echo "示例:"
    echo "GEMINI_API_KEY=your_api_key_here"
    echo "GEMINI_MODEL=gemini-2.5-flash"
    echo ""
fi

# 停止旧的后端进程(如果存在)
if [ -f "$PROJECT_DIR/logs/backend.pid" ]; then
    OLD_PID=$(cat "$PROJECT_DIR/logs/backend.pid")
    if ps -p $OLD_PID > /dev/null 2>&1; then
        echo "停止旧的后端进程 (PID: $OLD_PID)..."
        kill $OLD_PID
        sleep 2
    fi
fi

# 强制杀死占用8088端口的进程
echo "检查端口8088占用情况..."
fuser -k 8088/tcp 2>/dev/null || true
sleep 1

# 启动后端
echo "启动后端服务 (端口 8088)..."
nohup python -m uvicorn app.main:app --host 0.0.0.0 --port 8088 \
    > "$PROJECT_DIR/logs/backend.log" 2>&1 &
BACKEND_PID=$!
echo $BACKEND_PID > "$PROJECT_DIR/logs/backend.pid"
echo "✓ 后端已启动 (PID: $BACKEND_PID)"
echo "  日志文件: $PROJECT_DIR/logs/backend.log"

# 等待后端启动
echo "等待后端服务就绪..."
sleep 5

# 2. 启动前端服务
echo ""
echo "[2/2] 启动前端服务..."
cd "$FRONTEND_DIR"

# 检查 node_modules
if [ ! -d "node_modules" ]; then
    echo "安装前端依赖..."
    npm install
fi

# 停止旧的前端进程(如果存在)
if [ -f "$PROJECT_DIR/logs/frontend.pid" ]; then
    OLD_PID=$(cat "$PROJECT_DIR/logs/frontend.pid")
    if ps -p $OLD_PID > /dev/null 2>&1; then
        echo "停止旧的前端进程 (PID: $OLD_PID)..."
        kill $OLD_PID
        sleep 2
    fi
fi

# 启动前端
echo "启动前端服务 (端口 3100)..."
nohup npx vite --host 0.0.0.0 --port 3100 \
    > "$PROJECT_DIR/logs/frontend.log" 2>&1 &
FRONTEND_PID=$!
echo $FRONTEND_PID > "$PROJECT_DIR/logs/frontend.pid"
echo "✓ 前端已启动 (PID: $FRONTEND_PID)"
echo "  日志文件: $PROJECT_DIR/logs/frontend.log"

# 完成
echo ""
echo "=========================================="
echo "✓ 所有服务已启动完成!"
echo "=========================================="
echo ""
echo "服务信息:"
echo "  后端 API: http://localhost:8088"
echo "  API 文档: http://localhost:8088/docs"
echo "  前端界面: http://localhost:3100"
echo ""
echo "进程 ID:"
echo "  后端 PID: $BACKEND_PID"
echo "  前端 PID: $FRONTEND_PID"
echo ""
echo "日志文件:"
echo "  后端日志: $PROJECT_DIR/logs/backend.log"
echo "  前端日志: $PROJECT_DIR/logs/frontend.log"
echo ""
echo "管理命令:"
echo "  查看状态: ./status_services.sh"
echo "  停止服务: ./stop_services.sh"
echo "  查看日志: tail -f logs/backend.log"
echo "           tail -f logs/frontend.log"
echo ""
