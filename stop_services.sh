#!/bin/bash

# 停止前后端服务的脚本

PROJECT_DIR="/root/usr/skill_agent_demo"

echo "=========================================="
echo "停止 Skill Agent Demo 服务"
echo "=========================================="

# 停止后端
if [ -f "$PROJECT_DIR/logs/backend.pid" ]; then
    BACKEND_PID=$(cat "$PROJECT_DIR/logs/backend.pid")
    if ps -p $BACKEND_PID > /dev/null 2>&1; then
        echo "停止后端服务 (PID: $BACKEND_PID)..."
        kill $BACKEND_PID
        rm "$PROJECT_DIR/logs/backend.pid"
        echo "✓ 后端已停止"
    else
        echo "后端进程不存在 (PID: $BACKEND_PID)"
        rm "$PROJECT_DIR/logs/backend.pid"
    fi
else
    echo "未找到后端 PID 文件"
fi

# 停止前端
if [ -f "$PROJECT_DIR/logs/frontend.pid" ]; then
    FRONTEND_PID=$(cat "$PROJECT_DIR/logs/frontend.pid")
    if ps -p $FRONTEND_PID > /dev/null 2>&1; then
        echo "停止前端服务 (PID: $FRONTEND_PID)..."
        kill $FRONTEND_PID
        rm "$PROJECT_DIR/logs/frontend.pid"
        echo "✓ 前端已停止"
    else
        echo "前端进程不存在 (PID: $FRONTEND_PID)"
        rm "$PROJECT_DIR/logs/frontend.pid"
    fi
else
    echo "未找到前端 PID 文件"
fi

echo ""
echo "✓ 所有服务已停止"

