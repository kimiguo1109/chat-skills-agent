#!/bin/bash
# ============================================
# External Chat Web API 完整测试脚本 v1.0
# ============================================
#
# 🔥 测试 Web 专用接口（SSE 流式 + Intent + Skill + Edit/Regenerate）
#
# 测试场景：
# Part 1:  基础对话测试 (4轮) - 验证 Intent Router + Skill
# Part 2:  技能识别 (6轮) - Quiz/Flashcard/Explain + 0-token
# Part 3:  Plan Skill (2轮) - 部分组合
# Part 4:  上下文管理 (3轮) - 历史关联
# Part 5:  引用文本+快捷按钮 (3轮) - referenced_text + action_type
# Part 6:  文件上传 (3轮) - 图片/文档
# Part 7:  Edit 功能 (2轮) - 编辑历史消息
# Part 8:  Regenerate 功能 (2轮) - 重新生成
# Part 9:  Clear Session (2轮) - 清除会话
# Part 10: 版本历史+树结构 (2轮) - 获取版本
#
# 总计 29 轮测试
# ============================================

API_BASE="http://13.52.175.51:8088"
API_URL="${API_BASE}/api/external/chat/web"
API_HEALTH="${API_BASE}/api/studyx-agent/health"

# 🔥 固定 User 和 Question/Answer ID
USER_ID="web_test_user_$(date +%s)"
QUESTION_ID="WEBQ$(date +%s)"
ANSWER_ID="WEBA001"

# 📁 测试文件资源 (GCS)
FILE_IMAGE="gs://kimi-dev/images.jpeg"
FILE_GEOMETRY="gs://kimi-dev/450ffcb787fb42d0b0aeda4135d57a9f.jpg"
FILE_ERIE="gs://kimi-dev/ap 美国历史sample.txt"

# User Token
USER_TOKEN="eyJ0eXBlIjoiSldUIiwiZXhwIjoxNzY2ODE1NjQyLCJhbGciOiJIUzI1NiIsImlhdCI6MTc2NTUxOTY0Mn0.eyJyb2xlY29kZSI6IjMwIiwidXNlcmd1aWQiOiIxOTU3OTg1MDY5MzMxMjU1Mjk2In0.fe14fecd9ffaabf6eb7d20fd46943a77"

# 计数器
TOTAL_TESTS=0
PASSED_TESTS=0
FAILED_TESTS=0
TOTAL_TOKENS=0
TURN=0

# 颜色
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
NC='\033[0m'

print_header() {
    echo ""
    echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║  $1${NC}"
    echo -e "${BLUE}╚════════════════════════════════════════════════════════════╝${NC}"
}

print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

print_info() {
    echo -e "${YELLOW}📌 $1${NC}"
}

# ============================================
# SSE 测试函数 - 发送消息
# ============================================
test_web_chat() {
    local message="$1"
    local description="$2"
    local action="${3:-send}"
    local turn_id="${4:-}"
    local expected_intent="${5:-}"
    local timeout="${6:-90}"
    
    TOTAL_TESTS=$((TOTAL_TESTS + 1))
    TURN=$((TURN + 1))
    
    echo ""
    echo -e "${YELLOW}📝 测试 #$TOTAL_TESTS (T$TURN): $description${NC}"
    echo "   💬 消息: $message"
    echo "   🎯 Action: $action"
    
    local turn_param=""
    if [ -n "$turn_id" ]; then
        turn_param=", \"turn_id\": $turn_id"
        echo "   🔄 Turn ID: $turn_id"
    fi
    
    # 发送 SSE 请求并捕获 done 事件
    RESPONSE=$(curl -s -N --max-time "$timeout" -X POST "$API_URL" \
        -H "Content-Type: application/json" \
        -H "token: $USER_TOKEN" \
        -d "{
            \"message\": \"$message\",
            \"user_id\": \"$USER_ID\",
            \"question_id\": \"$QUESTION_ID\",
            \"answer_id\": \"$ANSWER_ID\",
            \"action\": \"$action\"$turn_param
        }" 2>&1 | grep "data:" | tail -1)
    
    if [ -z "$RESPONSE" ]; then
        print_error "请求超时或无响应"
        FAILED_TESTS=$((FAILED_TESTS + 1))
        return 1
    fi
    
    # 解析 SSE 数据
    JSON_DATA=$(echo "$RESPONSE" | sed 's/data: //')
    
    EVENT_TYPE=$(echo "$JSON_DATA" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('type',''))" 2>/dev/null)
    
    if [ "$EVENT_TYPE" == "done" ]; then
        INTENT=$(echo "$JSON_DATA" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('intent','N/A'))" 2>/dev/null)
        CONTENT_TYPE=$(echo "$JSON_DATA" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('content_type','N/A'))" 2>/dev/null)
        TOPIC=$(echo "$JSON_DATA" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('topic','')[:20])" 2>/dev/null)
        ELAPSED=$(echo "$JSON_DATA" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('elapsed_time',0))" 2>/dev/null)
        ACTUAL_TURN=$(echo "$JSON_DATA" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('turn_id',0))" 2>/dev/null)
        RESPONSE_TEXT=$(echo "$JSON_DATA" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('full_response','')[:80])" 2>/dev/null)
        
        echo "   📊 结果:"
        echo "      • Event: done | Intent: $INTENT | Type: $CONTENT_TYPE"
        echo "      • Topic: $TOPIC | Turn: $ACTUAL_TURN | Time: ${ELAPSED}s"
        echo "      • 💬 回复: ${RESPONSE_TEXT}..."
        
        # 验证 intent
        if [ -n "$expected_intent" ]; then
            case "$expected_intent" in
                "chat"|"other")
                    if [ "$INTENT" == "other" ]; then
                        echo "      • ✅ 正确识别为对话 (other)"
                    fi
                    ;;
                "quiz")
                    if [[ "$INTENT" == *"quiz"* ]]; then
                        echo "      • ✅ 正确识别为 Quiz"
                    fi
                    ;;
                "flashcard")
                    if [[ "$INTENT" == *"flashcard"* ]]; then
                        echo "      • ✅ 正确识别为 Flashcard"
                    fi
                    ;;
                "explain")
                    if [[ "$INTENT" == *"explain"* ]]; then
                        echo "      • ✅ 正确识别为 Explain"
                    fi
                    ;;
            esac
        fi
        
        print_success "PASSED"
        PASSED_TESTS=$((PASSED_TESTS + 1))
        
        # 保存实际 turn_id 供后续测试使用
        LAST_TURN_ID=$ACTUAL_TURN
        
    elif [ "$EVENT_TYPE" == "error" ]; then
        ERROR_MSG=$(echo "$JSON_DATA" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('message',''))" 2>/dev/null)
        echo "   📊 结果: Error - $ERROR_MSG"
        print_error "FAILED"
        FAILED_TESTS=$((FAILED_TESTS + 1))
    else
        echo "   📊 结果: 未知事件类型 - $EVENT_TYPE"
        echo "   原始响应: $RESPONSE"
        print_error "FAILED"
        FAILED_TESTS=$((FAILED_TESTS + 1))
    fi
    
    sleep 1
}

# ============================================
# 引用文本 + 快捷按钮测试
# ============================================
test_web_chat_with_reference() {
    local message="$1"
    local referenced_text="$2"
    local action_type="$3"
    local description="$4"
    local timeout="${5:-90}"
    
    TOTAL_TESTS=$((TOTAL_TESTS + 1))
    TURN=$((TURN + 1))
    
    echo ""
    echo -e "${YELLOW}📝 测试 #$TOTAL_TESTS (T$TURN): $description${NC}"
    echo "   💬 消息: $message"
    echo "   📎 引用: ${referenced_text:0:40}..."
    echo "   ⚡ Action Type: $action_type"
    
    local ref_param=""
    if [ -n "$referenced_text" ]; then
        ref_param=", \"referenced_text\": \"$referenced_text\""
    fi
    
    local action_param=""
    if [ -n "$action_type" ]; then
        action_param=", \"action_type\": \"$action_type\""
    fi
    
    RESPONSE=$(curl -s -N --max-time "$timeout" -X POST "$API_URL" \
        -H "Content-Type: application/json" \
        -H "token: $USER_TOKEN" \
        -d "{
            \"message\": \"$message\",
            \"user_id\": \"$USER_ID\",
            \"question_id\": \"$QUESTION_ID\",
            \"answer_id\": \"$ANSWER_ID\",
            \"action\": \"send\"$ref_param$action_param
        }" 2>&1 | grep "data:" | tail -1)
    
    JSON_DATA=$(echo "$RESPONSE" | sed 's/data: //')
    EVENT_TYPE=$(echo "$JSON_DATA" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('type',''))" 2>/dev/null)
    
    if [ "$EVENT_TYPE" == "done" ]; then
        INTENT=$(echo "$JSON_DATA" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('intent','N/A'))" 2>/dev/null)
        echo "   📊 结果: Event=done | Intent=$INTENT"
        print_success "PASSED"
        PASSED_TESTS=$((PASSED_TESTS + 1))
    else
        print_error "FAILED"
        FAILED_TESTS=$((FAILED_TESTS + 1))
    fi
    
    sleep 1
}

# ============================================
# 文件上传测试
# ============================================
test_web_chat_with_files() {
    local message="$1"
    local file_uris="$2"
    local description="$3"
    local timeout="${4:-90}"
    
    TOTAL_TESTS=$((TOTAL_TESTS + 1))
    TURN=$((TURN + 1))
    
    echo ""
    echo -e "${YELLOW}📝 测试 #$TOTAL_TESTS (T$TURN): $description${NC}"
    echo "   💬 消息: $message"
    echo "   📁 文件: $file_uris"
    
    RESPONSE=$(curl -s -N --max-time "$timeout" -X POST "$API_URL" \
        -H "Content-Type: application/json" \
        -H "token: $USER_TOKEN" \
        -d "{
            \"message\": \"$message\",
            \"user_id\": \"$USER_ID\",
            \"question_id\": \"$QUESTION_ID\",
            \"answer_id\": \"$ANSWER_ID\",
            \"action\": \"send\",
            \"file_uris\": $file_uris
        }" 2>&1 | grep "data:" | tail -1)
    
    JSON_DATA=$(echo "$RESPONSE" | sed 's/data: //')
    EVENT_TYPE=$(echo "$JSON_DATA" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('type',''))" 2>/dev/null)
    
    if [ "$EVENT_TYPE" == "done" ]; then
        INTENT=$(echo "$JSON_DATA" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('intent','N/A'))" 2>/dev/null)
        RESPONSE_TEXT=$(echo "$JSON_DATA" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('full_response','')[:60])" 2>/dev/null)
        echo "   📊 结果: Event=done | Intent=$INTENT"
        echo "      • 💬 回复: ${RESPONSE_TEXT}..."
        print_success "PASSED"
        PASSED_TESTS=$((PASSED_TESTS + 1))
    else
        print_error "FAILED"
        FAILED_TESTS=$((FAILED_TESTS + 1))
    fi
    
    sleep 1
}

# ============================================
# Clear Session 测试
# ============================================
test_clear_session() {
    local description="$1"
    
    TOTAL_TESTS=$((TOTAL_TESTS + 1))
    TURN=$((TURN + 1))
    
    echo ""
    echo -e "${YELLOW}📝 测试 #$TOTAL_TESTS (T$TURN): $description${NC}"
    echo "   🗑️ 清除会话: q${QUESTION_ID}_a${ANSWER_ID}"
    
    RESPONSE=$(curl -s --max-time 10 -X POST "${API_URL}/clear" \
        -H "Content-Type: application/json" \
        -d "{
            \"user_id\": \"$USER_ID\",
            \"question_id\": \"$QUESTION_ID\",
            \"answer_id\": \"$ANSWER_ID\"
        }")
    
    CODE=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('code','N/A'))" 2>/dev/null)
    MSG=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('msg',''))" 2>/dev/null)
    PREV_TURNS=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',{}).get('previous_turns',0))" 2>/dev/null)
    
    echo "   📊 结果: Code=$CODE | Msg=$MSG | Previous Turns=$PREV_TURNS"
    
    if [ "$CODE" == "0" ]; then
        print_success "PASSED"
        PASSED_TESTS=$((PASSED_TESTS + 1))
    else
        print_error "FAILED"
        FAILED_TESTS=$((FAILED_TESTS + 1))
    fi
    
    sleep 0.5
}

# ============================================
# 版本历史测试
# ============================================
test_get_versions() {
    local description="$1"
    local turn_id="$2"
    
    TOTAL_TESTS=$((TOTAL_TESTS + 1))
    TURN=$((TURN + 1))
    
    echo ""
    echo -e "${YELLOW}📝 测试 #$TOTAL_TESTS (T$TURN): $description${NC}"
    
    local turn_param=""
    if [ -n "$turn_id" ]; then
        turn_param="&turn_id=$turn_id"
    fi
    
    RESPONSE=$(curl -s --max-time 10 "${API_URL}/versions?user_id=$USER_ID&question_id=$QUESTION_ID&answer_id=$ANSWER_ID$turn_param")
    
    CODE=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('code','N/A'))" 2>/dev/null)
    TOTAL_VERSIONS=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',{}).get('total_versions',0))" 2>/dev/null)
    
    echo "   📊 结果: Code=$CODE | Total Versions=$TOTAL_VERSIONS"
    
    if [ "$CODE" == "0" ]; then
        print_success "PASSED"
        PASSED_TESTS=$((PASSED_TESTS + 1))
    else
        print_error "FAILED"
        FAILED_TESTS=$((FAILED_TESTS + 1))
    fi
    
    sleep 0.5
}

# ============================================
# 聊天树结构测试
# ============================================
test_get_chat_tree() {
    local description="$1"
    
    TOTAL_TESTS=$((TOTAL_TESTS + 1))
    TURN=$((TURN + 1))
    
    echo ""
    echo -e "${YELLOW}📝 测试 #$TOTAL_TESTS (T$TURN): $description${NC}"
    
    RESPONSE=$(curl -s --max-time 10 "${API_URL}/tree?user_id=$USER_ID&question_id=$QUESTION_ID&answer_id=$ANSWER_ID")
    
    CODE=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('code','N/A'))" 2>/dev/null)
    CURRENT_TURNS=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',{}).get('current_turns',0))" 2>/dev/null)
    VERSION_COUNT=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',{}).get('version_count',0))" 2>/dev/null)
    
    echo "   📊 结果: Code=$CODE | Current Turns=$CURRENT_TURNS | Version Count=$VERSION_COUNT"
    
    if [ "$CODE" == "0" ]; then
        print_success "PASSED"
        PASSED_TESTS=$((PASSED_TESTS + 1))
    else
        print_error "FAILED"
        FAILED_TESTS=$((FAILED_TESTS + 1))
    fi
    
    sleep 0.5
}

# ============================================
# 会话状态测试
# ============================================
test_get_status() {
    local description="$1"
    
    TOTAL_TESTS=$((TOTAL_TESTS + 1))
    TURN=$((TURN + 1))
    
    echo ""
    echo -e "${YELLOW}📝 测试 #$TOTAL_TESTS (T$TURN): $description${NC}"
    
    RESPONSE=$(curl -s --max-time 10 "${API_URL}/status?user_id=$USER_ID&question_id=$QUESTION_ID&answer_id=$ANSWER_ID")
    
    CODE=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('code','N/A'))" 2>/dev/null)
    TURN_COUNT=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',{}).get('turn_count',0))" 2>/dev/null)
    IS_PROCESSING=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',{}).get('is_processing',False))" 2>/dev/null)
    
    echo "   📊 结果: Code=$CODE | Turn Count=$TURN_COUNT | Processing=$IS_PROCESSING"
    
    if [ "$CODE" == "0" ]; then
        print_success "PASSED"
        PASSED_TESTS=$((PASSED_TESTS + 1))
    else
        print_error "FAILED"
        FAILED_TESTS=$((FAILED_TESTS + 1))
    fi
    
    sleep 0.5
}

# ============================================
# 健康检查
# ============================================
health_check() {
    print_header "🏥 健康检查"
    
    RESPONSE=$(curl -s --max-time 5 "$API_HEALTH")
    CODE=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('code','N/A'))" 2>/dev/null)
    
    if [ "$CODE" == "0" ]; then
        print_success "服务正常运行"
        echo "   • API: $API_URL"
        return 0
    else
        print_error "服务不可用"
        return 1
    fi
}

# ============================================
# 主测试流程
# ============================================

print_header "🌐 External Chat Web API 完整测试 v1.0"
echo ""
echo "📍 API: $API_URL"
echo "👤 User: $USER_ID"
echo "❓ Question: $QUESTION_ID"
echo "📝 Answer: $ANSWER_ID"

# 健康检查
if ! health_check; then
    echo "❌ 服务不可用，退出测试"
    exit 1
fi

# ============================================
# Part 1: 基础对话测试 (4轮)
# ============================================
print_header "💬 Part 1: 基础对话测试 (4轮)"
print_info "验证 SSE 流式输出 + Intent Router"

test_web_chat "你好，我想学习物理" "问候+学习意向" "send" "" "other"
test_web_chat "什么是牛顿第一定律" "概念询问" "send" "" "other"
test_web_chat "能举个例子说明惯性吗" "要求举例" "send" "" "other"
test_web_chat "好的，我明白了" "简单回应" "send" "" "other"

# ============================================
# Part 2: 技能识别 (6轮)
# ============================================
print_header "🎯 Part 2: 技能识别 (6轮)"
print_info "验证 Quiz/Flashcard/Explain 技能执行"

test_web_chat "给我两道物理选择题" "Quiz 请求" "send" "" "quiz" "120"
test_web_chat "做三张牛顿定律的闪卡" "Flashcard 请求" "send" "" "flashcard" "120"
test_web_chat "详细讲解一下牛顿第二定律" "Explain 请求" "send" "" "explain" "120"
test_web_chat "出一道惯性相关的题" "Quiz (跟进)" "send" "" "quiz" "120"
test_web_chat "帮我做两张力学闪卡" "Flashcard (跟进)" "send" "" "flashcard" "120"
test_web_chat "解释一下加速度" "Explain (跟进)" "send" "" "explain" "120"

# ============================================
# Part 3: Plan Skill (2轮)
# ============================================
print_header "📋 Part 3: Plan Skill (2轮)"
print_info "验证多技能组合"

test_web_chat "先讲解动能，然后出一道题" "讲解+出题组合" "send" "" "" "180"
test_web_chat "做两张功和能的闪卡，再出一道选择题" "闪卡+出题组合" "send" "" "" "180"

# ============================================
# Part 4: 上下文管理 (3轮)
# ============================================
print_header "🔄 Part 4: 上下文管理 (3轮)"
print_info "验证对话历史关联"

test_web_chat "我们之前讨论了什么" "回溯检索" "send" "" "other"
test_web_chat "继续讲讲能量守恒" "继续追问" "send" "" "other"
test_web_chat "总结一下今天学的内容" "上下文总结" "send" "" "other"

# ============================================
# Part 5: 引用文本 + 快捷按钮 (3轮)
# ============================================
print_header "📎 Part 5: 引用文本 + 快捷按钮 (3轮)"
print_info "验证 referenced_text 和 action_type"

test_web_chat_with_reference \
    "这一步我不明白" \
    "F=ma，所以当质量为2kg，加速度为3m/s²时，力为6N" \
    "" \
    "引用文本+问题"

test_web_chat_with_reference \
    "" \
    "动能公式 E=1/2mv²" \
    "explain_concept" \
    "引用文本+Explain按钮"

test_web_chat_with_reference \
    "" \
    "能量守恒定律" \
    "common_mistakes" \
    "引用文本+Common Mistakes"

# ============================================
# Part 6: 文件上传 (3轮)
# ============================================
print_header "📁 Part 6: 文件上传 (3轮)"
print_info "验证图片/文档上传"

test_web_chat_with_files \
    "这张图片是什么" \
    "[\"$FILE_IMAGE\"]" \
    "单图片识别"

test_web_chat_with_files \
    "这道几何题怎么解" \
    "[\"$FILE_GEOMETRY\"]" \
    "几何图片解题"

test_web_chat_with_files \
    "这个文档讲了什么" \
    "[\"$FILE_ERIE\"]" \
    "单文档分析"

# ============================================
# Part 7: Edit 功能 (2轮)
# ============================================
print_header "✏️ Part 7: Edit 功能 (2轮)"
print_info "验证编辑历史消息功能"

# 记录当前 turn
EDIT_TURN=$((LAST_TURN_ID - 2))
if [ $EDIT_TURN -lt 1 ]; then
    EDIT_TURN=1
fi

test_web_chat "用更简单的方式解释牛顿定律" "Edit 消息 (Turn $EDIT_TURN)" "edit" "$EDIT_TURN" "other"

# 发送新消息验证 Edit 后的上下文
test_web_chat "刚才的解释清楚了吗" "Edit 后追问" "send" "" "other"

# ============================================
# Part 8: Regenerate 功能 (2轮)
# ============================================
print_header "🔄 Part 8: Regenerate 功能 (2轮)"
print_info "验证重新生成功能"

# 重新生成上一轮
REGEN_TURN=$LAST_TURN_ID
if [ -z "$REGEN_TURN" ] || [ "$REGEN_TURN" == "0" ]; then
    REGEN_TURN=1
fi

test_web_chat "" "Regenerate (Turn $REGEN_TURN)" "regenerate" "$REGEN_TURN" ""

# 发送新消息验证 Regenerate 后的上下文
test_web_chat "这次的回答更好了" "Regenerate 后追问" "send" "" "other"

# ============================================
# Part 9: 版本历史 + 树结构 (3轮)
# ============================================
print_header "📜 Part 9: 版本历史 + 树结构 (3轮)"
print_info "验证 Edit/Regenerate 版本追踪"

test_get_versions "获取所有版本"
test_get_chat_tree "获取聊天树结构"
test_get_status "获取会话状态"

# ============================================
# Part 10: Clear Session (2轮)
# ============================================
print_header "🗑️ Part 10: Clear Session (2轮)"
print_info "验证清除会话功能"

test_clear_session "清除会话"

# 验证清除后可以重新开始
test_web_chat "你好，我们重新开始" "清除后新消息" "send" "" "other"

# ============================================
# 测试报告
# ============================================
print_header "📊 测试报告 - Web API 完整测试"

PASS_RATE=$(echo "scale=1; $PASSED_TESTS * 100 / $TOTAL_TESTS" | bc 2>/dev/null || echo "N/A")

echo ""
echo "╔════════════════════════════════════════════════════════════╗"
echo "║          🌐 Web API 测试结果                               ║"
echo "╠════════════════════════════════════════════════════════════╣"
printf "║  %-56s ║\n" "User ID: $USER_ID"
printf "║  %-56s ║\n" "Question ID: $QUESTION_ID"
printf "║  %-56s ║\n" "Answer ID: $ANSWER_ID"
printf "║  %-56s ║\n" "总对话轮数: $TURN"
echo "╠════════════════════════════════════════════════════════════╣"
printf "║  %-56s ║\n" "总测试数: $TOTAL_TESTS"
printf "║  %-56s ║\n" "通过: $PASSED_TESTS"
printf "║  %-56s ║\n" "失败: $FAILED_TESTS"
printf "║  %-56s ║\n" "通过率: ${PASS_RATE}%"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""

if [ $FAILED_TESTS -eq 0 ]; then
    echo -e "${GREEN}🎉 所有测试通过！${NC}"
else
    echo -e "${YELLOW}⚠️  有 $FAILED_TESTS 个测试失败${NC}"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📌 测试覆盖 (${TURN}轮):"
echo "   Part 1:  基础对话 → SSE + Intent Router"
echo "   Part 2:  技能识别 → Quiz/Flashcard/Explain"
echo "   Part 3:  Plan Skill → 多技能组合"
echo "   Part 4:  上下文管理 → 历史关联"
echo "   Part 5:  引用文本 → referenced_text + action_type"
echo "   Part 6:  文件上传 → 图片/文档"
echo "   Part 7:  Edit → 编辑历史消息"
echo "   Part 8:  Regenerate → 重新生成"
echo "   Part 9:  版本历史 → 树结构"
echo "   Part 10: Clear Session → 清除会话"
echo ""
echo "📂 会话记录:"
echo "   backend/artifacts/${USER_ID}/q${QUESTION_ID}_a${ANSWER_ID}.md"
echo "   backend/artifacts/${USER_ID}/q${QUESTION_ID}_a${ANSWER_ID}_versions.json"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

