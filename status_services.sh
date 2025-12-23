#!/bin/bash

# 查看服务状态的脚本

PROJECT_DIR="/root/usr/skill_agent_demo"

echo "=========================================="
echo "Skill Agent Demo 服务状态"
echo "=========================================="
echo ""

# 检查后端状态
echo "【后端服务】"
if [ -f "$PROJECT_DIR/logs/backend.pid" ]; then
    BACKEND_PID=$(cat "$PROJECT_DIR/logs/backend.pid")
    if ps -p $BACKEND_PID > /dev/null 2>&1; then
        echo "  状态: ✓ 运行中"
        echo "  PID: $BACKEND_PID"
        echo "  端口: 8088"
        echo "  URL: http://13.52.175.51:8088"
        echo "  文档: http://13.52.175.51:8088/docs"
    else
        echo "  状态: ✗ 已停止 (PID 文件存在但进程不存在)"
    fi
else
    echo "  状态: ✗ 未运行"
fi

echo ""

# 检查前端状态
echo "【前端服务】"
if [ -f "$PROJECT_DIR/logs/frontend.pid" ]; then
    FRONTEND_PID=$(cat "$PROJECT_DIR/logs/frontend.pid")
    if ps -p $FRONTEND_PID > /dev/null 2>&1; then
        echo "  状态: ✓ 运行中"
        echo "  PID: $FRONTEND_PID"
        echo "  端口: 8089"
        echo "  URL: http://13.52.175.51:8089"
    else
        echo "  状态: ✗ 已停止 (PID 文件存在但进程不存在)"
    fi
else
    echo "  状态: ✗ 未运行"
fi

echo ""
echo "=========================================="
echo ""
echo "查看日志:"
echo "  后端: tail -f $PROJECT_DIR/logs/backend.log"
echo "  前端: tail -f $PROJECT_DIR/logs/frontend.log"
echo ""

