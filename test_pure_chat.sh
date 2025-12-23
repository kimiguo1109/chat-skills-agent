#!/bin/bash
# ============================================
# Pure Chat API 完整测试脚本
# 端点: /api/chat/send
# 功能: 纯 Chat + 上下文管理 + 智能检索 + 跨时间会话恢复 + 压缩归档
# ============================================

API_URL="http://13.52.175.51:8088/api/chat/send"
USER_ID="pure_chat_test"
NEW_SESSION_ID="session_$(date +%s)"
OLD_SESSION_ID="session_1764323548"  # 历史会话
SESSION_ID="$NEW_SESSION_ID"

# 文件资源
FILE_ERIE="gs://kimi-dev/ap 美国历史sample.txt"
FILE_COLD_WAR="gs://kimi-dev/ap 美国历史sample 2.txt"
FILE_IMAGE="gs://kimi-dev/images.jpeg"
FILE_GEOMETRY="gs://kimi-dev/450ffcb787fb42d0b0aeda4135d57a9f.jpg"

# 计数器
TOTAL_TESTS=0
PASSED_TESTS=0
TOTAL_TOKENS=0

# 颜色
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "╔════════════════════════════════════════════════════════════╗"
echo "║           🧪 Pure Chat API 完整测试                        ║"
echo "║           端点: /api/chat/send                             ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""
echo "📍 API: $API_URL"
echo "👤 User: $USER_ID"
echo "📋 新会话: $NEW_SESSION_ID"
echo "📋 历史会话: $OLD_SESSION_ID"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# 测试函数
test_chat() {
    local message="$1"
    local description="$2"
    local file_uris="$3"
    
    TOTAL_TESTS=$((TOTAL_TESTS + 1))
    
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "📝 测试 #$TOTAL_TESTS: $description"
    echo "💬 消息: $message"
    [ -n "$file_uris" ] && echo "📎 文件: $file_uris"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    
    if [ -n "$file_uris" ]; then
        REQUEST_BODY="{\"message\": \"$message\", \"file_uris\": $file_uris, \"user_id\": \"$USER_ID\", \"session_id\": \"$SESSION_ID\"}"
    else
        REQUEST_BODY="{\"message\": \"$message\", \"user_id\": \"$USER_ID\", \"session_id\": \"$SESSION_ID\"}"
    fi
    
    RESPONSE=$(curl -s -X POST "$API_URL" -H "Content-Type: application/json" -d "$REQUEST_BODY")
    
    CODE=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('code','N/A'))" 2>/dev/null)
    TEXT=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',{}).get('text','N/A')[:80])" 2>/dev/null)
    SESSION_TURNS=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',{}).get('context_stats',{}).get('session_turns',0))" 2>/dev/null)
    LOADED_TURNS=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',{}).get('context_stats',{}).get('loaded_turns',0))" 2>/dev/null)
    RETRIEVED_TURNS=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',{}).get('context_stats',{}).get('retrieved_turns',0))" 2>/dev/null)
    TOKEN_TOTAL=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',{}).get('token_usage',{}).get('total',{}).get('total',0))" 2>/dev/null)
    GEN_TIME=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',{}).get('generation_time',0))" 2>/dev/null)
    
    echo "📊 结果:"
    echo "   • Code: $CODE"
    echo "   • Turn: $SESSION_TURNS (加载: $LOADED_TURNS, 检索: $RETRIEVED_TURNS)"
    echo "   • Token: $TOKEN_TOTAL"
    echo "   • 耗时: ${GEN_TIME}s"
    echo "   • 回复: $TEXT..."
    
    if [ "$CODE" == "0" ]; then
        echo "   ✅ PASSED"
        PASSED_TESTS=$((PASSED_TESTS + 1))
        TOTAL_TOKENS=$((TOTAL_TOKENS + TOKEN_TOTAL))
    else
        echo "   ❌ FAILED"
    fi
    echo ""
    sleep 1
}

# 检查 Session 文件状态
check_session_files() {
    local session_id="$1"
    local session_dir="/root/usr/skill_agent_demo/backend/artifacts/$USER_ID"
    
    echo -e "${BLUE}📁 Session 文件状态${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    
    if [ -f "$session_dir/${session_id}.md" ]; then
        local lines=$(wc -l < "$session_dir/${session_id}.md")
        local chars=$(wc -c < "$session_dir/${session_id}.md")
        echo "📄 MD 文件: $lines 行, $chars 字符"
    fi
    
    # 检查归档文件
    local archives=$(ls "$session_dir/${session_id}_archive"*.md 2>/dev/null | wc -l)
    if [ "$archives" -gt 0 ]; then
        echo -e "${GREEN}📦 归档文件: $archives 个${NC}"
        ls -la "$session_dir/${session_id}_archive"*.md 2>/dev/null
    else
        echo "📦 归档文件: 无 (需超过30轮触发压缩)"
    fi
    echo ""
}

echo "🔄 开始测试..."
echo ""

# ============================================
# Part 1: 基础对话 (5轮)
# ============================================
echo "╔════════════════════════════════════════╗"
echo "║     Part 1: 基础对话                   ║"
echo "╚════════════════════════════════════════╝"
test_chat "你好，我想学习牛顿三大定律" "开始学习"
test_chat "先讲讲第一定律吧" "追问第一定律"
test_chat "什么是惯性" "深入惯性"
test_chat "能举个汽车的例子吗" "请求举例"
test_chat "好的，讲讲第二定律" "继续学习"

# ============================================
# Part 2: 深入学习 (5轮)
# ============================================
echo "╔════════════════════════════════════════╗"
echo "║     Part 2: 深入学习 (窗口卸载)        ║"
echo "╚════════════════════════════════════════╝"
test_chat "F=ma 这个公式怎么用" "F=ma 公式"
test_chat "如果质量是5kg，加速度是2，力是多少" "计算题"
test_chat "第三定律呢" "继续第三定律"
test_chat "什么是作用力和反作用力" "深入作用力"
test_chat "帮我总结一下牛顿三大定律" "总结"

# ============================================
# Part 3: 主题切换 (3轮)
# ============================================
echo "╔════════════════════════════════════════╗"
echo "║     Part 3: 主题切换                   ║"
echo "╚════════════════════════════════════════╝"
test_chat "换个话题，讲讲化学键" "切换化学"
test_chat "什么是共价键" "共价键"
test_chat "好，换成历史，二战是怎么开始的" "切换历史"

# ============================================
# Part 4: 智能检索测试 (3轮)
# ============================================
echo "╔════════════════════════════════════════╗"
echo "║     Part 4: 🔎 智能检索测试            ║"
echo "╚════════════════════════════════════════╝"
test_chat "回到最开始讲的物理，惯性是什么来着" "时间引用"
test_chat "第一个问题讲的是什么" "索引引用"
test_chat "牛顿定律那部分内容我没太懂" "关键词引用"

# ============================================
# Part 5: 多模态 (5轮)
# ============================================
echo "╔════════════════════════════════════════╗"
echo "║     Part 5: 📷📄 多模态测试            ║"
echo "╚════════════════════════════════════════╝"
test_chat "这张图片是什么" "图片识别" "[\"$FILE_IMAGE\"]"
test_chat "图中的结构有什么功能" "图片追问"
test_chat "这个文件讲了什么" "单文档分析" "[\"$FILE_ERIE\"]"
test_chat "比较这两个文件" "多文档比较" "[\"$FILE_ERIE\", \"$FILE_COLD_WAR\"]"
test_chat "伊利运河对美国经济有什么影响" "文档追问"

# ============================================
# Part 6: 复杂上下文 (4轮)
# ============================================
echo "╔════════════════════════════════════════╗"
echo "║     Part 6: 复杂上下文引用             ║"
echo "╚════════════════════════════════════════╝"
test_chat "刚才那个公式怎么用来着" "模糊引用"
test_chat "我还是不太懂，能再解释一次吗" "请求重复"
test_chat "这个知识点和之前的化学有关系吗" "跨主题关联"
test_chat "帮我总结今天学的所有内容" "全局总结"

# 检查新会话文件状态
check_session_files "$NEW_SESSION_ID"

# ============================================
# Part 7: 🔄 跨时间会话恢复
# ============================================
echo "╔════════════════════════════════════════╗"
echo "║     Part 7: 🔄 跨时间会话恢复          ║"
echo "║     (历史 session_1764323548)          ║"
echo "╚════════════════════════════════════════╝"
echo "📌 切换到历史会话: $OLD_SESSION_ID"
SESSION_ID="$OLD_SESSION_ID"

test_chat "你好，我回来了" "历史会话恢复"
test_chat "我们之前学了什么内容" "历史内容回忆"
test_chat "F=ma 的计算题再给我讲一遍" "历史知识点引用"
test_chat "之前的化学键和共价键还记得吗" "跨主题历史回忆"
test_chat "伊利运河的内容帮我复习一下" "历史文档回忆"

# ============================================
# Part 8: 深度上下文 (3轮)
# ============================================
echo "╔════════════════════════════════════════╗"
echo "║     Part 8: 📊 深度上下文测试          ║"
echo "╚════════════════════════════════════════╝"
test_chat "第一定律和第三定律有什么区别" "多知识点对比"
test_chat "能用一个例子同时解释三大定律吗" "综合运用"
test_chat "如果我开车，这三个定律怎么体现" "实际应用"

# ============================================
# Part 9: 精确引用 (3轮)
# ============================================
echo "╔════════════════════════════════════════╗"
echo "║     Part 9: 🎯 精确引用测试            ║"
echo "╚════════════════════════════════════════╝"
test_chat "你之前举的汽车例子是什么" "具体内容引用"
test_chat "质量5kg加速度2的那道题答案是多少" "计算结果引用"
test_chat "凡尔赛条约在我们的对话里提到过吗" "历史关键词搜索"

# 检查历史会话文件状态 (含归档检测)
check_session_files "$OLD_SESSION_ID"

# ============================================
# Part 10: 多轮深度对话 (切回新会话)
# ============================================
echo "╔════════════════════════════════════════╗"
echo "║     Part 10: 📚 多轮深度对话           ║"
echo "╚════════════════════════════════════════╝"
SESSION_ID="$NEW_SESSION_ID"
echo "📌 切换回新会话: $SESSION_ID"

test_chat "这道几何题怎么解" "几何图片" "[\"$FILE_GEOMETRY\"]"
test_chat "能详细说说解题步骤吗" "图片追问"
test_chat "现在教我微积分" "新主题"
test_chat "什么是导数" "导数概念"
test_chat "导数的几何意义是什么" "导数深入"
test_chat "f(x)=x²的导数是多少" "导数计算"
test_chat "那积分呢" "切换积分"
test_chat "定积分和不定积分有什么区别" "积分深入"
test_chat "微积分和牛顿定律有关系吗" "跨领域关联"

# ============================================
# Part 11: 最终回顾
# ============================================
echo "╔════════════════════════════════════════╗"
echo "║     Part 11: 🔁 最终回顾测试           ║"
echo "╚════════════════════════════════════════╝"
test_chat "回到最开始，我们聊了什么" "长程时间引用"
test_chat "今天一共学了几个主题" "全局统计"
test_chat "帮我做一个完整的学习总结" "最终总结"

# 最终文件状态检查
echo "╔════════════════════════════════════════╗"
echo "║     📁 最终文件状态检查                ║"
echo "╚════════════════════════════════════════╝"
check_session_files "$NEW_SESSION_ID"
check_session_files "$OLD_SESSION_ID"

# ============================================
# 测试总结
# ============================================
echo ""
echo "╔════════════════════════════════════════════════════════╗"
echo "║                    📊 测试报告                         ║"
echo "╚════════════════════════════════════════════════════════╝"
echo ""
echo "  总测试数: $TOTAL_TESTS"
echo "  ✅ 通过: $PASSED_TESTS"
echo "  ❌ 失败: $((TOTAL_TESTS - PASSED_TESTS))"
echo "  📊 总 Token: $TOTAL_TOKENS"
if [ $TOTAL_TESTS -gt 0 ]; then
    echo "  📊 平均 Token/轮: $((TOTAL_TOKENS / TOTAL_TESTS))"
fi
echo ""

if [ $PASSED_TESTS -eq $TOTAL_TESTS ]; then
    echo "  🎉 所有测试通过！"
else
    echo "  ⚠️ 有 $((TOTAL_TESTS - PASSED_TESTS)) 个测试失败"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📁 Session 目录:"
echo "   /root/usr/skill_agent_demo/backend/artifacts/$USER_ID/"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
