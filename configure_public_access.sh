#!/bin/bash

# 自动配置公网访问的脚本

set -e

PROJECT_DIR="/root/usr/skill_agent_demo"

echo "=========================================="
echo "配置公网访问"
echo "=========================================="
echo ""

# 获取公网 IP
echo "正在获取公网 IP..."
PUBLIC_IP=$(curl -s http://checkip.amazonaws.com || curl -s ifconfig.me || curl -s icanhazip.com)

if [ -z "$PUBLIC_IP" ]; then
    echo "❌ 无法获取公网 IP"
    exit 1
fi

echo "✓ 检测到公网 IP: $PUBLIC_IP"
echo ""

# 备份原始文件
echo "备份配置文件..."
cp "$PROJECT_DIR/frontend/public/demo.html" "$PROJECT_DIR/frontend/public/demo.html.backup"
if [ -f "$PROJECT_DIR/backend/.env" ]; then
    cp "$PROJECT_DIR/backend/.env" "$PROJECT_DIR/backend/.env.backup"
fi
echo "✓ 备份完成"
echo ""

# 更新 demo.html
echo "更新 demo.html API 地址..."
sed -i "s|const API_BASE = 'http://localhost:8088';|const API_BASE = 'http://$PUBLIC_IP:8088';|" \
    "$PROJECT_DIR/frontend/public/demo.html"
sed -i "s|const API_BASE = 'http://[0-9.]*:8088';|const API_BASE = 'http://$PUBLIC_IP:8088';|" \
    "$PROJECT_DIR/frontend/public/demo.html"
echo "✓ demo.html 已更新"
echo ""

# 更新 CORS 配置
if [ -f "$PROJECT_DIR/backend/.env" ]; then
    echo "更新后端 CORS 配置..."
    # 读取当前的 CORS_ORIGINS
    CURRENT_CORS=$(grep "^CORS_ORIGINS=" "$PROJECT_DIR/backend/.env" | cut -d'=' -f2 || echo "")
    
    # 检查是否已包含公网 IP
    if [[ $CURRENT_CORS == *"$PUBLIC_IP"* ]]; then
        echo "ℹ️  CORS 配置已包含公网 IP"
    else
        # 添加公网 IP 到 CORS
        if [ -z "$CURRENT_CORS" ]; then
            NEW_CORS="http://$PUBLIC_IP:3100"
        else
            NEW_CORS="$CURRENT_CORS,http://$PUBLIC_IP:3100"
        fi
        sed -i "s|^CORS_ORIGINS=.*|CORS_ORIGINS=$NEW_CORS|" "$PROJECT_DIR/backend/.env"
        echo "✓ CORS 配置已更新"
    fi
    echo ""
fi

# 重启服务
echo "重启服务以应用配置..."
cd "$PROJECT_DIR"
./stop_services.sh > /dev/null 2>&1 || true
sleep 2
./start_services.sh > /dev/null 2>&1 || true
echo "✓ 服务已重启"
echo ""

echo "=========================================="
echo "✓ 配置完成!"
echo "=========================================="
echo ""
echo "📊 访问信息:"
echo ""
echo "  公网 IP: $PUBLIC_IP"
echo ""
echo "  后端 API: http://$PUBLIC_IP:8088"
echo "  API 文档: http://$PUBLIC_IP:8088/docs"
echo "  前端页面: http://$PUBLIC_IP:3100/demo.html"
echo ""
echo "=========================================="
echo ""
echo "⚠️  重要提醒:"
echo ""
echo "1. 确保 AWS 安全组已开放端口:"
echo "   - 端口 8088 (后端 API)"
echo "   - 端口 3100 (前端界面)"
echo ""
echo "2. 在 AWS EC2 控制台配置安全组:"
echo "   - 进入 EC2 → 实例 → 安全 → 安全组"
echo "   - 编辑入站规则"
echo "   - 添加规则: 自定义 TCP, 端口 8088, 源 0.0.0.0/0"
echo "   - 添加规则: 自定义 TCP, 端口 3100, 源 0.0.0.0/0"
echo ""
echo "3. 测试访问:"
echo "   在浏览器中打开: http://$PUBLIC_IP:3100/demo.html"
echo ""
echo "=========================================="
echo ""

