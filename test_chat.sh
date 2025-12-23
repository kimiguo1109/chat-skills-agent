#!/bin/bash
# ============================================
# External Chat 完整测试脚本 v5.0 - 前端交付版
# ============================================
#
# 🔥 核心测试目标：验证所有前端所需功能
#
# 测试场景：
# Part 1:  随机对话 Chat (4轮) - 验证对话类消息
# Part 2:  技能识别 (6轮) - Quiz/Flashcard/Explain + 0-token
# Part 3:  Plan Skill (2轮) - 部分组合
# Part 4:  上下文管理 (5轮) - 历史关联 + 上下文统计
# Part 5:  真伪思考 (4轮) - 新/旧 topic 的思考模式
# Part 6:  引导式提问 (3轮) - 模糊请求的澄清
# Part 7:  LLM Fallback (2轮) - 边界情况
# Part 8:  混合技能测试 (4轮) - 多技能组合
# Part 9:  引用文本+快捷按钮 (5轮) - referenced_text + action_type
# Part 10: 文件上传 (6轮) - 图片/文档/多文件
# Part 11: 引用文本+Skill (3轮) - referenced_text + quiz/flashcard
# Part 12: 题目关联聊天 (4轮) - question_id + answer_id 绑定
# Part 13: 反馈 API (3轮) - like/dislike/report
# Part 14: Token Header (2轮) - 用户 Token 传递
# Part 15: 输出格式验证 (3轮) - 所有输出为 text 格式
# Part 16: 🆕 统一 files 数组 (5轮) - 多图片/多文档/混合上传
#
# 总计 61 轮测试
# ============================================

API_BASE="http://13.52.175.51:8088"
API_URL="${API_BASE}/api/external/chat"
API_HEALTH="${API_BASE}/api/studyx-agent/health"

# 🔥 固定 User 和 Session，模拟已登录用户的长对话
USER_ID="long_context_user_$(date +%s)"
SESSION_ID="long_session_$(date +%Y%m%d_%H%M%S)"

# 📁 测试文件资源 (GCS)
FILE_ERIE="gs://kimi-dev/ap 美国历史sample.txt"
FILE_COLD_WAR="gs://kimi-dev/ap 美国历史sample 2.txt"
FILE_IMAGE="gs://kimi-dev/images.jpeg"
FILE_GEOMETRY="gs://kimi-dev/450ffcb787fb42d0b0aeda4135d57a9f.jpg"

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

print_thinking() {
    echo -e "${MAGENTA}🧠 $1${NC}"
}

# ============================================
# 引用文本测试函数
# ============================================
test_chat_with_reference() {
    local message="$1"
    local referenced_text="$2"
    local description="$3"
    local expected_intent="$4"
    local timeout="${5:-60}"
    
    TOTAL_TESTS=$((TOTAL_TESTS + 1))
    TURN=$((TURN + 1))
    
    echo ""
    echo -e "${YELLOW}📝 测试 #$TOTAL_TESTS (T$TURN): $description${NC}"
    echo "   💬 消息: $message"
    echo "   📎 引用: ${referenced_text:0:50}..."
    
    RESPONSE=$(curl -s --max-time "$timeout" -X POST "$API_URL" \
        -H "Content-Type: application/json" \
        -d "{\"message\": \"$message\", \"referenced_text\": \"$referenced_text\", \"user_id\": \"$USER_ID\", \"session_id\": \"$SESSION_ID\"}")
    
    if [ -z "$RESPONSE" ]; then
        print_error "请求超时或无响应"
        FAILED_TESTS=$((FAILED_TESTS + 1))
        return 1
    fi
    
    CODE=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('code','N/A'))" 2>/dev/null)
    INTENT=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',{}).get('intent','N/A'))" 2>/dev/null)
    CONTENT_TYPE=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',{}).get('content_type','N/A'))" 2>/dev/null)
    
    echo "   📊 结果: Intent=$INTENT | Type=$CONTENT_TYPE | Code=$CODE"
    
    if [ "$CODE" == "0" ]; then
        TEXT=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); c=d.get('data',{}).get('content',{}); print((c.get('text','') if isinstance(c,dict) else str(c))[:80])" 2>/dev/null)
        echo "      • 💬 回复: ${TEXT}..."
        print_success "PASSED"
        PASSED_TESTS=$((PASSED_TESTS + 1))
    else
        MSG=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('msg',''))" 2>/dev/null)
        echo "      • ⚠️ 错误: $MSG"
        print_error "FAILED"
        FAILED_TESTS=$((FAILED_TESTS + 1))
    fi
    
    sleep 0.5
}

# ============================================
# 快捷按钮测试函数
# ============================================
test_quick_action() {
    local action_type="$1"
    local description="$2"
    local timeout="${3:-60}"
    
    TOTAL_TESTS=$((TOTAL_TESTS + 1))
    TURN=$((TURN + 1))
    
    echo ""
    echo -e "${YELLOW}📝 测试 #$TOTAL_TESTS (T$TURN): $description${NC}"
    echo "   ⚡ 快捷操作: $action_type"
    
    RESPONSE=$(curl -s --max-time "$timeout" -X POST "$API_URL" \
        -H "Content-Type: application/json" \
        -d "{\"message\": \"\", \"action_type\": \"$action_type\", \"user_id\": \"$USER_ID\", \"session_id\": \"$SESSION_ID\"}")
    
    if [ -z "$RESPONSE" ]; then
        print_error "请求超时或无响应"
        FAILED_TESTS=$((FAILED_TESTS + 1))
        return 1
    fi
    
    CODE=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('code','N/A'))" 2>/dev/null)
    INTENT=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',{}).get('intent','N/A'))" 2>/dev/null)
    
    echo "   📊 结果: Intent=$INTENT | Code=$CODE"
    
    if [ "$CODE" == "0" ]; then
        TEXT=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); c=d.get('data',{}).get('content',{}); print((c.get('text','') if isinstance(c,dict) else str(c))[:80])" 2>/dev/null)
        echo "      • 💬 回复: ${TEXT}..."
        print_success "PASSED"
        PASSED_TESTS=$((PASSED_TESTS + 1))
    else
        MSG=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('msg',''))" 2>/dev/null)
        echo "      • ⚠️ 错误: $MSG"
        print_error "FAILED"
        FAILED_TESTS=$((FAILED_TESTS + 1))
    fi
    
    sleep 0.5
}

# ============================================
# 引用文本验证测试（应该失败）
# ============================================
test_reference_validation() {
    local referenced_text="$1"
    local description="$2"
    
    TOTAL_TESTS=$((TOTAL_TESTS + 1))
    TURN=$((TURN + 1))
    
    echo ""
    echo -e "${YELLOW}📝 测试 #$TOTAL_TESTS (T$TURN): $description${NC}"
    echo "   📎 引用: ${referenced_text:0:50}..."
    echo "   💬 消息: (空)"
    
    RESPONSE=$(curl -s --max-time 10 -X POST "$API_URL" \
        -H "Content-Type: application/json" \
        -d "{\"message\": \"\", \"referenced_text\": \"$referenced_text\", \"user_id\": \"$USER_ID\", \"session_id\": \"$SESSION_ID\"}")
    
    CODE=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('code','N/A'))" 2>/dev/null)
    MSG=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('msg',''))" 2>/dev/null)
    
    echo "   📊 结果: Code=$CODE"
    
    if [ "$CODE" == "400" ]; then
        echo "      • ✅ 正确拒绝: $MSG"
        print_success "PASSED (正确返回400)"
        PASSED_TESTS=$((PASSED_TESTS + 1))
    else
        echo "      • ⚠️ 应该返回400错误"
        print_error "FAILED"
        FAILED_TESTS=$((FAILED_TESTS + 1))
    fi
    
    sleep 0.5
}

# ============================================
# 📁 文件上传测试函数
# ============================================
test_chat_with_files() {
    local message="$1"
    local file_uris="$2"  # JSON 数组格式: ["gs://...", "gs://..."]
    local description="$3"
    local expected_intent="$4"
    local timeout="${5:-90}"
    
    TOTAL_TESTS=$((TOTAL_TESTS + 1))
    TURN=$((TURN + 1))
    
    echo ""
    echo -e "${YELLOW}📝 测试 #$TOTAL_TESTS (T$TURN): $description${NC}"
    echo "   💬 消息: $message"
    echo "   📁 文件: $file_uris"
    
    RESPONSE=$(curl -s --max-time "$timeout" -X POST "$API_URL" \
        -H "Content-Type: application/json" \
        -d "{\"message\": \"$message\", \"file_uris\": $file_uris, \"user_id\": \"$USER_ID\", \"session_id\": \"$SESSION_ID\"}")
    
    if [ -z "$RESPONSE" ]; then
        print_error "请求超时或无响应"
        FAILED_TESTS=$((FAILED_TESTS + 1))
        return 1
    fi
    
    CODE=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('code','N/A'))" 2>/dev/null)
    INTENT=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',{}).get('intent','N/A'))" 2>/dev/null)
    CONTENT_TYPE=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',{}).get('content_type','N/A'))" 2>/dev/null)
    TOKEN_TOTAL=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',{}).get('token_usage',{}).get('total_internal_tokens',0))" 2>/dev/null)
    
    echo "   📊 结果:"
    echo "      • Intent: $INTENT | Type: $CONTENT_TYPE | Code: $CODE"
    
    if [ "$TOKEN_TOTAL" != "0" ] && [ "$TOKEN_TOTAL" != "N/A" ] && [ -n "$TOKEN_TOTAL" ]; then
        TOTAL_TOKENS=$((TOTAL_TOKENS + TOKEN_TOTAL))
        echo "      • Token: $TOKEN_TOTAL"
    fi
    
    if [ "$CODE" == "0" ]; then
        # 显示回复内容
        case "$CONTENT_TYPE" in
            "quiz_set")
                Q_COUNT=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('data',{}).get('content',{}).get('questions',[])))" 2>/dev/null)
                echo "      • 📝 Quiz: $Q_COUNT 道题"
                ;;
            "flashcard_set")
                C_COUNT=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('data',{}).get('content',{}).get('cardList',[])))" 2>/dev/null)
                echo "      • 🃏 Flashcard: $C_COUNT 张卡"
                ;;
            *)
                TEXT=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); c=d.get('data',{}).get('content',{}); print((c.get('text','') if isinstance(c,dict) else str(c))[:80])" 2>/dev/null)
                echo "      • 💬 回复: ${TEXT}..."
                ;;
        esac
        
        print_success "PASSED"
        PASSED_TESTS=$((PASSED_TESTS + 1))
    else
        MSG=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('msg',''))" 2>/dev/null)
        echo "      • ❌ 错误: $MSG"
        print_error "FAILED"
        FAILED_TESTS=$((FAILED_TESTS + 1))
    fi
    
    sleep 1
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
# 测试函数
# ============================================
test_chat() {
    local message="$1"
    local description="$2"
    local expected_intent="$3"
    local check_context="$4"
    local timeout="${5:-60}"  # 默认60秒，Plan Skill可能需要更长
    
    TOTAL_TESTS=$((TOTAL_TESTS + 1))
    TURN=$((TURN + 1))
    
    echo ""
    echo -e "${YELLOW}📝 测试 #$TOTAL_TESTS (T$TURN): $description${NC}"
    echo "   💬 消息: $message"
    
    RESPONSE=$(curl -s --max-time "$timeout" -X POST "$API_URL" \
        -H "Content-Type: application/json" \
        -d "{\"message\": \"$message\", \"user_id\": \"$USER_ID\", \"session_id\": \"$SESSION_ID\"}")
    
    # 检查是否有响应
    if [ -z "$RESPONSE" ]; then
        print_error "请求超时或无响应"
        FAILED_TESTS=$((FAILED_TESTS + 1))
        return 1
    fi
    
    CODE=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('code','N/A'))" 2>/dev/null)
    CONTENT_TYPE=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',{}).get('content_type','N/A'))" 2>/dev/null)
    INTENT=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',{}).get('intent','N/A'))" 2>/dev/null)
    TOPIC=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',{}).get('topic','')[:20])" 2>/dev/null)
    
    # Token 统计
    TOKEN_TOTAL=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',{}).get('token_usage',{}).get('total_internal_tokens',0))" 2>/dev/null)
    INTENT_TOKENS=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',{}).get('token_usage',{}).get('intent_router',{}).get('tokens',0))" 2>/dev/null)
    INTENT_SOURCE=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',{}).get('token_usage',{}).get('intent_router',{}).get('method','N/A'))" 2>/dev/null)
    
    # Context 统计
    LOADED=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',{}).get('context_stats',{}).get('loaded_turns',0))" 2>/dev/null)
    SESSION_TURNS=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',{}).get('context_stats',{}).get('session_turns',0))" 2>/dev/null)
    
    if [ "$TOKEN_TOTAL" != "0" ] && [ "$TOKEN_TOTAL" != "N/A" ] && [ -n "$TOKEN_TOTAL" ]; then
        TOTAL_TOKENS=$((TOTAL_TOKENS + TOKEN_TOTAL))
    fi
    
    echo "   📊 结果:"
    echo "      • Intent: $INTENT | Type: $CONTENT_TYPE | Topic: $TOPIC"
    echo "      • Intent Router: $INTENT_SOURCE ($INTENT_TOKENS tokens)"
    
    if [ "$check_context" == "yes" ]; then
        echo "      • 上下文: 加载=$LOADED轮, 会话=$SESSION_TURNS轮"
    fi
    
    # 验证结果
    PASS=true
    
    if [ "$CODE" != "0" ]; then
        PASS=false
        echo "      • ❌ 请求失败 (code=$CODE)"
    fi
    
    # 检查 intent 匹配
    if [ -n "$expected_intent" ]; then
        case "$expected_intent" in
            "chat"|"other")
                if [ "$INTENT" == "other" ]; then
                    echo "      • ✅ 正确识别为对话 (other)"
                else
                    echo "      • ⚠️ 预期对话(other)，实际: $INTENT"
                fi
                ;;
            "quiz")
                if [[ "$INTENT" == *"quiz"* ]]; then
                    echo "      • ✅ 正确识别为 Quiz"
                else
                    echo "      • ⚠️ 预期 quiz，实际: $INTENT"
                    PASS=false
                fi
                ;;
            "flashcard")
                if [[ "$INTENT" == *"flashcard"* ]]; then
                    echo "      • ✅ 正确识别为 Flashcard"
                else
                    echo "      • ⚠️ 预期 flashcard，实际: $INTENT"
                    PASS=false
                fi
                ;;
            "explain")
                if [[ "$INTENT" == *"explain"* ]]; then
                    echo "      • ✅ 正确识别为 Explain"
                else
                    echo "      • ⚠️ 预期 explain，实际: $INTENT"
                    PASS=false
                fi
                ;;
            "plan"|"learning_bundle")
                if [[ "$INTENT" == *"learning"* ]] || [[ "$INTENT" == *"bundle"* ]]; then
                    echo "      • ✅ 正确识别为 Plan/Learning Bundle"
                else
                    echo "      • ⚠️ 预期 learning_bundle，实际: $INTENT"
                fi
                ;;
            "clarification")
                if [[ "$INTENT" == *"clarification"* ]] || [[ "$CONTENT_TYPE" == *"clarification"* ]]; then
                    echo "      • ✅ 正确触发澄清"
                else
                    echo "      • ⚠️ 预期 clarification，实际: $INTENT"
                fi
                ;;
            "0-token")
                if [ "$INTENT_SOURCE" == "skill_registry" ] && [ "$INTENT_TOKENS" == "0" ]; then
                    echo "      • ✅ 0-token 匹配成功"
                else
                    echo "      • ⚠️ 预期 0-token，实际: $INTENT_SOURCE ($INTENT_TOKENS tokens)"
                fi
                ;;
            "context")
                if [ "$LOADED" != "0" ] && [ "$LOADED" != "N/A" ]; then
                    echo "      • ✅ 上下文加载成功 ($LOADED 轮)"
                else
                    echo "      • ⚠️ 上下文未加载"
                fi
                ;;
        esac
    fi
    
    # 显示内容摘要
    case "$CONTENT_TYPE" in
        "quiz_set")
            Q_COUNT=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('data',{}).get('content',{}).get('questions',[])))" 2>/dev/null)
            echo "      • 📝 Quiz: $Q_COUNT 道题"
            ;;
        "flashcard_set")
            C_COUNT=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('data',{}).get('content',{}).get('cardList',[])))" 2>/dev/null)
            echo "      • 🃏 Flashcard: $C_COUNT 张卡"
            ;;
        "explanation")
            echo "      • 📚 Explanation 已生成"
            ;;
        "learning_bundle")
            COMPONENTS=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); c=d.get('data',{}).get('content',{}); comps=c.get('components',[]); print(len(comps))" 2>/dev/null)
            echo "      • 📋 Learning Bundle: $COMPONENTS 个组件"
            ;;
        "clarification_needed"|"clarification")
            TEXT=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); c=d.get('data',{}).get('content',{}); print((c.get('text','') if isinstance(c,dict) else str(c))[:60])" 2>/dev/null)
            echo "      • ❓ 澄清问题: ${TEXT}..."
            ;;
        "text"|*)
            TEXT=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); c=d.get('data',{}).get('content',{}); print((c.get('text','') if isinstance(c,dict) else str(c))[:60])" 2>/dev/null)
            echo "      • 💬 回复: ${TEXT}..."
            ;;
    esac
    
    if [ "$PASS" == "true" ]; then
        print_success "PASSED"
            PASSED_TESTS=$((PASSED_TESTS + 1))
    else
        print_error "FAILED"
        FAILED_TESTS=$((FAILED_TESTS + 1))
    fi
    
    sleep 0.5
}

# ============================================
# 主测试流程
# ============================================

print_header "🧪 External Chat 完整测试 v2.0"
echo ""
echo "📍 API: $API_URL"
echo "👤 User: $USER_ID"
echo "📋 Session: $SESSION_ID"

# 健康检查
if ! health_check; then
    echo "❌ 服务不可用，退出测试"
    exit 1
fi

# ============================================
# Part 1: 随机对话 Chat (4轮)
# ============================================
print_header "💬 Part 1: 随机对话 Chat (4轮)"
print_info "验证对话类消息正确识别为 'other'"

test_chat "你好，我想学习物理" "问候+学习意向" "chat" ""
test_chat "什么是惯性" "概念询问" "chat" ""
test_chat "能举个例子吗" "要求举例" "chat" ""
test_chat "今天天气怎么样" "闲聊" "chat" ""

# ============================================
# Part 2: 技能识别 (6轮)
# ============================================
print_header "🎯 Part 2: 技能识别 (6轮)"
print_info "验证 Skill 请求被正确识别 + 0-token 匹配"

test_chat "给我三道光合作用的题目" "Quiz 请求" "quiz" "" "120"
test_chat "做五张化学键的闪卡" "Flashcard 请求" "flashcard" "" "120"
test_chat "详细讲解一下细胞呼吸" "Explain 请求" "explain" "" "120"
test_chat "出两道牛顿定律的题" "Quiz (0-token验证)" "0-token" "" "120"
test_chat "帮我做三张元素周期表的闪卡" "Flashcard 请求" "flashcard" "" "120"
test_chat "解释一下牛顿第二定律" "Explain 请求" "explain" "" "120"

# ============================================
# Part 3: Plan Skill (3轮) - 精简版
# ============================================
print_header "📋 Part 3: Plan Skill (3轮)"
print_info "验证学习计划请求 + 部分组合"

# 部分组合: 讲解 + 出题 (只执行 explain + quiz, 更快)
test_chat "先讲解光合作用然后出两道题" "讲解+出题组合" "plan" "" "180"

# 部分组合: 闪卡 + 题目 (只执行 flashcard + quiz, 更快)
test_chat "做3张DNA的闪卡和2道题" "闪卡+出题组合" "plan" "" "180"

# 完整学习计划 (5个组件，需要更长时间) - 放到最后，可选跳过
# test_chat "帮我制定一个完整的物理学习计划" "完整学习计划" "plan" "" "300"

# ============================================
# Part 4: 上下文管理 (5轮) - 继续同一 Session
# ============================================
print_header "🔄 Part 4: 上下文管理 (5轮)"
print_info "验证对话历史关联 + 上下文统计（基于前面的对话历史）"

# 🔥 不新建 session，继续在同一个长对话中测试上下文管理

test_chat "我们来学习二战历史" "新主题开始" "chat" "yes" "60"
test_chat "二战是哪一年开始的" "上下文追问1" "context" "yes" "60"
test_chat "主要参战国有哪些" "上下文追问2" "context" "yes" "60"
test_chat "我们刚才说的是什么主题" "回溯检索" "context" "yes" "60"
test_chat "继续讲讲战争的影响" "继续追问" "context" "yes" "60"

# ============================================
# Part 5: 真伪思考模式 (4轮) - 继续同一 Session
# ============================================
print_header "🧠 Part 5: 真伪思考模式 (4轮)"
print_info "验证新/旧 topic 的思考模式选择（基于已有上下文）"

# 🔥 继续同一 session

print_thinking "场景1: 全新 Topic → 应触发真思考"
test_chat "详细讲解量子力学的基本原理" "新topic讲解" "explain" "" "120"

print_thinking "场景2: Follow-up → 应触发伪思考"
test_chat "给我出2道量子力学的题" "同topic出题" "quiz" "" "120"

print_thinking "场景3: 引用内容 → 应触发伪思考"
test_chat "第一道题的答案是什么" "引用特定内容" "chat" "" "60"

print_thinking "场景4: 新 Topic → 应触发真思考"
test_chat "解释一下DNA的结构和功能" "新topic讲解" "explain" "" "120"

# ============================================
# Part 6: 引导式提问 (3轮) - 继续同一 Session
# ============================================
print_header "❓ Part 6: 引导式提问 (3轮)"
print_info "验证模糊请求的澄清机制（有长对话历史背景）"

# 🔥 继续同一 session

test_chat "我想学习" "模糊请求-无主题" "clarification" ""
test_chat "帮我整理一下" "模糊请求-无具体内容" "clarification" ""
test_chat "做一些练习" "模糊请求-无主题" "clarification" ""

# ============================================
# Part 7: LLM Fallback (2轮) - 继续同一 Session
# ============================================
print_header "🤖 Part 7: LLM Fallback (2轮)"
print_info "验证边界情况的 LLM 辅助（基于已有学习记录）"

# 🔥 继续同一 session

test_chat "给我一些学习建议" "需要 LLM 判断" "" ""
test_chat "今天学习进度怎么样" "模糊问题" "" ""

# ============================================
# Part 8: 混合技能测试 (4轮) - 继续同一 Session
# ============================================
print_header "🔀 Part 8: 混合技能测试 (4轮)"
print_info "验证多种技能组合使用（完整长对话的最后阶段）"

# 🔥 继续同一 session

test_chat "详细讲解电磁感应的原理" "Explain 新 topic" "explain" "" "120"
test_chat "做3张电磁感应的闪卡" "Follow-up Flashcard" "flashcard" "" "120"
test_chat "出两道电磁感应的选择题" "Follow-up Quiz" "quiz" "" "120"
test_chat "总结一下我们刚才学了什么" "上下文总结" "chat" "" "60"

# ============================================
# Part 9: 引用文本 + 快捷按钮测试 (5轮)
# ============================================
print_header "📎 Part 9: 引用文本 + 快捷按钮 (5轮)"
print_info "验证新增的 referenced_text 和 action_type 字段"

# 测试引用文本 + 用户问题（正确流程）
test_chat_with_reference \
    "这一步我不太确定，能解释一下吗?" \
    "8x - 31 = -29，将 -31 移到右边得到 8x = -29 + 31 = 2，因此 x = 0.25" \
    "引用文本+用户问题" \
    "other"

# 测试引用文本验证（空消息应该失败）
test_reference_validation \
    "光的衍射是光波遇到障碍物时绕过边缘弯曲传播的现象" \
    "引用文本+空消息(应失败)"

# 测试快捷按钮 - explain_concept
test_quick_action "explain_concept" "快捷按钮: Explain the concept"

# 测试快捷按钮 - common_mistakes  
test_quick_action "common_mistakes" "快捷按钮: Common mistakes"

# 测试快捷按钮 - make_simpler
test_quick_action "make_simpler" "快捷按钮: Make it simpler"

# ============================================
# Part 10: 📁 文件上传测试 (6轮)
# ============================================
print_header "📁 Part 10: 文件上传测试 (6轮)"
print_info "验证图片/文档上传 + 多文件对比功能"

# 单图片识别
test_chat_with_files \
    "这张图片是什么" \
    "[\"$FILE_IMAGE\"]" \
    "单图片识别" \
    "other"

# 图片追问（无新文件）
test_chat "图中的内容有什么用途" "图片上下文追问" "chat" ""

# 单文档分析
test_chat_with_files \
    "这个文件讲了什么内容" \
    "[\"$FILE_ERIE\"]" \
    "单文档分析" \
    "other"

# 多文档对比
test_chat_with_files \
    "比较这两个文件的主要内容" \
    "[\"$FILE_ERIE\", \"$FILE_COLD_WAR\"]" \
    "多文档对比" \
    "other"

# 基于文档出题
test_chat_with_files \
    "根据这个文档出两道选择题" \
    "[\"$FILE_ERIE\"]" \
    "文档出题" \
    "quiz" \
    "120"

# 几何图片解题
test_chat_with_files \
    "这道几何题怎么解" \
    "[\"$FILE_GEOMETRY\"]" \
    "几何图片解题" \
    "other"

# ============================================
# Part 11: 引用文本 + Skill 生成 (3轮)
# ============================================
print_header "📎 Part 11: 引用文本 + Skill 生成 (3轮)"
print_info "验证引用文本场景下的 Skill 意图识别"

# 引用文本 + 出题
test_chat_with_reference \
    "根据这段内容出两道选择题" \
    "牛顿第二定律：F=ma，即力等于质量乘以加速度。这是经典力学中最重要的定律之一。" \
    "引用文本+出题" \
    "quiz"

# 引用文本 + 闪卡
test_chat_with_reference \
    "帮我做三张闪卡" \
    "光合作用是植物利用光能将二氧化碳和水转化为葡萄糖和氧气的过程。叶绿体是光合作用的场所。" \
    "引用文本+闪卡" \
    "flashcard"

# 引用文本 + 讲解
test_chat_with_reference \
    "详细讲解一下这个概念" \
    "量子隧穿效应是指微观粒子能够穿越经典物理学认为不可能穿越的势垒的量子力学现象。" \
    "引用文本+讲解" \
    "other"

# ============================================
# Part 12: 题目关联聊天 (4轮)
# ============================================
print_header "🔗 Part 12: 题目关联聊天 (4轮)"
print_info "验证 question_id + answer_id 绑定功能"

# 测试题目关联聊天
test_question_bound_chat() {
    local message="$1"
    local question_id="$2"
    local answer_id="$3"
    local description="$4"
    local referenced_text="$5"
    local timeout="${6:-60}"
    
    TOTAL_TESTS=$((TOTAL_TESTS + 1))
    TURN=$((TURN + 1))
    
echo ""
    echo -e "${YELLOW}📝 测试 #$TOTAL_TESTS (T$TURN): $description${NC}"
    echo "   💬 消息: $message"
    echo "   🔗 Question ID: $question_id"
    echo "   🔗 Answer ID: $answer_id"
    
    local ref_field=""
    if [ -n "$referenced_text" ]; then
        ref_field=", \"referenced_text\": \"$referenced_text\""
    fi
    
    RESPONSE=$(curl -s --max-time "$timeout" -X POST "$API_URL" \
        -H "Content-Type: application/json" \
        -d "{\"message\": \"$message\", \"question_id\": \"$question_id\", \"answer_id\": \"$answer_id\", \"user_id\": \"$USER_ID\"$ref_field}")
    
    if [ -z "$RESPONSE" ]; then
        print_error "请求超时或无响应"
        FAILED_TESTS=$((FAILED_TESTS + 1))
        return 1
    fi
    
    CODE=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('code','N/A'))" 2>/dev/null)
    INTENT=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',{}).get('intent','N/A'))" 2>/dev/null)
    LOADED=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',{}).get('context_stats',{}).get('loaded_turns',0))" 2>/dev/null)
    
    echo "   📊 结果: Intent=$INTENT | Code=$CODE | Loaded=$LOADED turns"
    
    if [ "$CODE" == "0" ]; then
        TEXT=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); c=d.get('data',{}).get('content',{}); print((c.get('text','') if isinstance(c,dict) else str(c))[:60])" 2>/dev/null)
        echo "      • 💬 回复: ${TEXT}..."
        print_success "PASSED"
    PASSED_TESTS=$((PASSED_TESTS + 1))
else
        MSG=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('msg',''))" 2>/dev/null)
        echo "      • ⚠️ 错误: $MSG"
        print_error "FAILED"
        FAILED_TESTS=$((FAILED_TESTS + 1))
    fi
    
    sleep 0.5
}

# 测试获取题目聊天历史
test_question_history() {
    local question_id="$1"
    local answer_id="$2"
    local description="$3"
    
TOTAL_TESTS=$((TOTAL_TESTS + 1))
    TURN=$((TURN + 1))
    
echo ""
    echo -e "${YELLOW}📝 测试 #$TOTAL_TESTS (T$TURN): $description${NC}"
    echo "   🔗 Question ID: $question_id"
    echo "   🔗 Answer ID: $answer_id"
    
    RESPONSE=$(curl -s --max-time 10 "${API_BASE}/api/external/chat/history?aiQuestionId=$question_id&answerId=$answer_id")
    
    CODE=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('code','N/A'))" 2>/dev/null)
    TOTAL=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',{}).get('total',0))" 2>/dev/null)
    SESSION=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',{}).get('session_id','N/A'))" 2>/dev/null)
    
    echo "   📊 结果: Code=$CODE | Total=$TOTAL turns | Session=$SESSION"
    
    if [ "$CODE" == "0" ]; then
        print_success "PASSED"
    PASSED_TESTS=$((PASSED_TESTS + 1))
else
        print_error "FAILED"
        FAILED_TESTS=$((FAILED_TESTS + 1))
    fi
    
    sleep 0.5
}

# 发送消息（绑定题目）
TEST_QID="QTEST$(date +%s)"
TEST_AID="ATEST001"

test_question_bound_chat \
    "这一步怎么从等式左边移到右边" \
    "$TEST_QID" \
    "$TEST_AID" \
    "题目绑定-第一条消息" \
    "8x - 31 = -29"

# 继续对话（同一题目）
test_question_bound_chat \
    "明白了，那下一步怎么求x的值" \
    "$TEST_QID" \
    "$TEST_AID" \
    "题目绑定-继续对话"

# 再问一个问题
test_question_bound_chat \
    "x的最终答案是多少" \
    "$TEST_QID" \
    "$TEST_AID" \
    "题目绑定-追问答案"

# 获取题目聊天历史
test_question_history "$TEST_QID" "$TEST_AID" "获取题目聊天历史"

# ============================================
# Part 13: 反馈 API (3轮)
# ============================================
print_header "👍 Part 13: 反馈 API (3轮)"
print_info "验证点赞/踩/报告功能"

test_feedback_api() {
    local feedback_type="$1"
    local turn_number="$2"
    local description="$3"
    local report_reason="$4"
    
    TOTAL_TESTS=$((TOTAL_TESTS + 1))
    TURN=$((TURN + 1))
    
echo ""
    echo -e "${YELLOW}📝 测试 #$TOTAL_TESTS (T$TURN): $description${NC}"
    echo "   👍 反馈类型: $feedback_type"
    
    local extra_fields=""
    if [ -n "$report_reason" ]; then
        extra_fields=", \"report_reason\": \"$report_reason\", \"report_detail\": \"测试报告\""
    fi
    
    RESPONSE=$(curl -s --max-time 10 -X POST "${API_BASE}/api/chat/feedback" \
        -H "Content-Type: application/json" \
        -d "{\"user_id\": \"$USER_ID\", \"session_id\": \"$SESSION_ID\", \"turn_number\": $turn_number, \"feedback_type\": \"$feedback_type\"$extra_fields}")
    
    CODE=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('code','N/A'))" 2>/dev/null)
    SUCCESS=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('success', d.get('code',1)==0))" 2>/dev/null)
    
    echo "   📊 结果: Code=$CODE | Success=$SUCCESS"
    
    if [ "$CODE" == "0" ] || [ "$SUCCESS" == "True" ]; then
        print_success "PASSED"
        PASSED_TESTS=$((PASSED_TESTS + 1))
    else
        print_error "FAILED"
        FAILED_TESTS=$((FAILED_TESTS + 1))
    fi
    
    sleep 0.5
}

# 点赞
test_feedback_api "like" 1 "提交点赞"

# 踩
test_feedback_api "dislike" 2 "提交踩"

# 报告问题
test_feedback_api "report" 3 "提交报告" "calculation_error"

# ============================================
# Part 14: Token Header 测试 (2轮)
# ============================================
print_header "🔑 Part 14: Token Header 测试 (2轮)"
print_info "验证用户 Token 传递（外部 Quiz/Flashcard API）"

test_with_token() {
    local message="$1"
    local description="$2"
    local token="$3"
    local timeout="${4:-90}"
    
    TOTAL_TESTS=$((TOTAL_TESTS + 1))
    TURN=$((TURN + 1))
    
echo ""
    echo -e "${YELLOW}📝 测试 #$TOTAL_TESTS (T$TURN): $description${NC}"
    echo "   💬 消息: $message"
    echo "   🔑 Token: ${token:0:30}..."
    
    RESPONSE=$(curl -s --max-time "$timeout" -X POST "$API_URL" \
        -H "Content-Type: application/json" \
        -H "token: $token" \
        -d "{\"message\": \"$message\", \"user_id\": \"$USER_ID\", \"session_id\": \"$SESSION_ID\"}")
    
    if [ -z "$RESPONSE" ]; then
        print_error "请求超时或无响应"
        FAILED_TESTS=$((FAILED_TESTS + 1))
        return 1
    fi
    
    CODE=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('code','N/A'))" 2>/dev/null)
    INTENT=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',{}).get('intent','N/A'))" 2>/dev/null)
    CONTENT_TYPE=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',{}).get('content_type','N/A'))" 2>/dev/null)
    
    echo "   📊 结果: Intent=$INTENT | Type=$CONTENT_TYPE | Code=$CODE"
    
    if [ "$CODE" == "0" ]; then
        TEXT=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); c=d.get('data',{}).get('content',{}); print((c.get('text','') if isinstance(c,dict) else str(c))[:60])" 2>/dev/null)
        echo "      • 💬 回复: ${TEXT}..."
        print_success "PASSED"
        PASSED_TESTS=$((PASSED_TESTS + 1))
    else
        MSG=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('msg',''))" 2>/dev/null)
        echo "      • ⚠️ 错误: $MSG"
        print_error "FAILED"
        FAILED_TESTS=$((FAILED_TESTS + 1))
    fi
    
    sleep 1
}

# 使用有效 Token 测试 Quiz
USER_TOKEN="eyJ0eXBlIjoiSldUIiwiZXhwIjoxNzY2ODE1NjQyLCJhbGciOiJIUzI1NiIsImlhdCI6MTc2NTUxOTY0Mn0.eyJyb2xlY29kZSI6IjMwIiwidXNlcmd1aWQiOiIxOTU3OTg1MDY5MzMxMjU1Mjk2In0.fe14fecd9ffaabf6eb7d20fd46943a77"

test_with_token \
    "给我一道物理选择题" \
    "Token Header + Quiz" \
    "$USER_TOKEN" \
    "120"

# 使用有效 Token 测试 Flashcard
test_with_token \
    "做两张数学闪卡" \
    "Token Header + Flashcard" \
    "$USER_TOKEN" \
    "120"

# ============================================
# Part 15: 输出格式验证 (3轮)
# ============================================
print_header "📋 Part 15: 输出格式验证 (3轮)"
print_info "验证所有 Skill 输出都转换为 text 格式"

# ============================================
# 🆕 统一 files 数组测试函数
# ============================================
test_chat_with_unified_files() {
    local message="$1"
    local file_uris="$2"      # GCS 文件 URI 数组 (JSON)
    local files_json="$3"      # 前端回显 files 数组 (JSON)
    local description="$4"
    local expected_intent="$5"
    local timeout="${6:-90}"
    
    TOTAL_TESTS=$((TOTAL_TESTS + 1))
    TURN=$((TURN + 1))
    
    echo ""
    echo -e "${YELLOW}📝 测试 #$TOTAL_TESTS (T$TURN): $description${NC}"
    echo "   💬 消息: $message"
    echo "   📁 file_uris: $file_uris"
    echo "   📦 files: $files_json"
    
    RESPONSE=$(curl -s --max-time "$timeout" -X POST "$API_URL" \
        -H "Content-Type: application/json" \
        -d "{\"message\": \"$message\", \"file_uris\": $file_uris, \"files\": $files_json, \"user_id\": \"$USER_ID\", \"session_id\": \"$SESSION_ID\"}")
    
    if [ -z "$RESPONSE" ]; then
        print_error "请求超时或无响应"
        FAILED_TESTS=$((FAILED_TESTS + 1))
        return 1
    fi
    
    CODE=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('code','N/A'))" 2>/dev/null)
    INTENT=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',{}).get('intent','N/A'))" 2>/dev/null)
    CONTENT_TYPE=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',{}).get('content_type','N/A'))" 2>/dev/null)
    TOKEN_TOTAL=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',{}).get('token_usage',{}).get('total_internal_tokens',0))" 2>/dev/null)
    
    echo "   📊 结果: Intent=$INTENT | Type=$CONTENT_TYPE | Code=$CODE"
    
    if [ "$TOKEN_TOTAL" != "0" ] && [ "$TOKEN_TOTAL" != "N/A" ] && [ -n "$TOKEN_TOTAL" ]; then
        TOTAL_TOKENS=$((TOTAL_TOKENS + TOKEN_TOTAL))
        echo "      • Token: $TOKEN_TOTAL"
    fi
    
    if [ "$CODE" == "0" ]; then
        TEXT=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); c=d.get('data',{}).get('content',{}); print((c.get('text','') if isinstance(c,dict) else str(c))[:80])" 2>/dev/null)
        echo "      • 💬 回复: ${TEXT}..."
        print_success "PASSED"
        PASSED_TESTS=$((PASSED_TESTS + 1))
    else
        MSG=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('msg',''))" 2>/dev/null)
        echo "      • ❌ 错误: $MSG"
        print_error "FAILED"
        FAILED_TESTS=$((FAILED_TESTS + 1))
    fi
    
    sleep 1
}

test_output_format() {
    local message="$1"
    local description="$2"
    local timeout="${3:-90}"
    
    TOTAL_TESTS=$((TOTAL_TESTS + 1))
    TURN=$((TURN + 1))
    
echo ""
    echo -e "${YELLOW}📝 测试 #$TOTAL_TESTS (T$TURN): $description${NC}"
    echo "   💬 消息: $message"
    
    RESPONSE=$(curl -s --max-time "$timeout" -X POST "$API_URL" \
        -H "Content-Type: application/json" \
        -H "token: $USER_TOKEN" \
        -d "{\"message\": \"$message\", \"user_id\": \"$USER_ID\", \"session_id\": \"$SESSION_ID\"}")
    
    if [ -z "$RESPONSE" ]; then
        print_error "请求超时或无响应"
        FAILED_TESTS=$((FAILED_TESTS + 1))
        return 1
    fi
    
    CODE=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('code','N/A'))" 2>/dev/null)
    CONTENT_TYPE=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',{}).get('content_type','N/A'))" 2>/dev/null)
    INTENT=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',{}).get('intent','N/A'))" 2>/dev/null)
    
    echo "   📊 结果: Intent=$INTENT | content_type=$CONTENT_TYPE"
    
    if [ "$CODE" == "0" ] && [ "$CONTENT_TYPE" == "text" ]; then
        echo "      • ✅ 输出格式正确: text"
        print_success "PASSED"
        PASSED_TESTS=$((PASSED_TESTS + 1))
    elif [ "$CODE" == "0" ]; then
        echo "      • ⚠️ 输出格式: $CONTENT_TYPE (预期 text)"
        print_error "FAILED"
        FAILED_TESTS=$((FAILED_TESTS + 1))
    else
        print_error "FAILED"
        FAILED_TESTS=$((FAILED_TESTS + 1))
    fi
    
    sleep 1
}

test_output_format "给我一道化学选择题" "Quiz → text 格式" "120"
test_output_format "做一张生物闪卡" "Flashcard → text 格式" "120"
test_output_format "详细讲解光的折射" "Explain → text 格式" "120"

# ============================================
# Part 16: 🆕 统一 files 数组测试 (5轮)
# ============================================
print_header "📦 Part 16: 统一 files 数组测试 (5轮)"
print_info "验证新的 files 数组结构支持多图片/多文档混合上传"

# 单图片 + files 回显
test_chat_with_unified_files \
    "这张图片是什么内容" \
    "[\"$FILE_IMAGE\"]" \
    "[{\"type\": \"image\", \"url\": \"https://cdn.studyx.com/images.jpeg\"}]" \
    "单图片 + files 回显" \
    "other"

# 单文档 + files 回显
test_chat_with_unified_files \
    "总结这份文档的要点" \
    "[\"$FILE_ERIE\"]" \
    "[{\"type\": \"document\", \"name\": \"AP美国历史笔记.txt\"}]" \
    "单文档 + files 回显" \
    "other"

# 多图片 + files 回显
test_chat_with_unified_files \
    "比较这两张图片有什么不同" \
    "[\"$FILE_IMAGE\", \"$FILE_GEOMETRY\"]" \
    "[{\"type\": \"image\", \"url\": \"https://cdn.studyx.com/images.jpeg\"}, {\"type\": \"image\", \"url\": \"https://cdn.studyx.com/geometry.jpg\"}]" \
    "多图片 + files 回显" \
    "other"

# 多文档 + files 回显
test_chat_with_unified_files \
    "对比这两份文档的核心内容" \
    "[\"$FILE_ERIE\", \"$FILE_COLD_WAR\"]" \
    "[{\"type\": \"document\", \"name\": \"AP美国历史1.txt\"}, {\"type\": \"document\", \"name\": \"AP美国历史2.txt\"}]" \
    "多文档 + files 回显" \
    "other"

# 图片+文档混合 + files 回显
test_chat_with_unified_files \
    "结合图片和文档帮我分析" \
    "[\"$FILE_GEOMETRY\", \"$FILE_ERIE\"]" \
    "[{\"type\": \"image\", \"url\": \"https://cdn.studyx.com/geometry.jpg\"}, {\"type\": \"document\", \"name\": \"参考资料.txt\"}]" \
    "图片+文档混合 + files 回显" \
    "other"

# ============================================
# 测试报告
# ============================================
print_header "📊 测试报告 - 单Session长对话测试"

PASS_RATE=$(echo "scale=1; $PASSED_TESTS * 100 / $TOTAL_TESTS" | bc 2>/dev/null || echo "N/A")

echo ""
echo "╔════════════════════════════════════════════════════════════╗"
echo "║          🔥 单 Session 长对话测试结果                      ║"
echo "╠════════════════════════════════════════════════════════════╣"
printf "║  %-56s ║\n" "User ID: $USER_ID"
printf "║  %-56s ║\n" "Session ID: $SESSION_ID"
printf "║  %-56s ║\n" "总对话轮数: $TURN"
echo "╠════════════════════════════════════════════════════════════╣"
printf "║  %-56s ║\n" "总测试数: $TOTAL_TESTS"
printf "║  %-56s ║\n" "通过: $PASSED_TESTS"
printf "║  %-56s ║\n" "失败: $FAILED_TESTS"
printf "║  %-56s ║\n" "通过率: ${PASS_RATE}%"
printf "║  %-56s ║\n" "总 Token: $TOTAL_TOKENS"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""

if [ $FAILED_TESTS -eq 0 ]; then
    echo -e "${GREEN}🎉 所有测试通过！${NC}"
else
    echo -e "${YELLOW}⚠️  有 $FAILED_TESTS 个测试失败${NC}"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📌 完整测试覆盖 (${TURN}轮连续对话):"
echo "   Part 1:  随机对话 → Intent: other"
echo "   Part 2:  技能识别 → Quiz/Flashcard/Explain + 0-token"
echo "   Part 3:  Plan Skill → 部分组合"
echo "   Part 4:  上下文管理 → 历史关联 + 回溯检索"
echo "   Part 5:  真伪思考 → 新topic真思考 / Follow-up伪思考"
echo "   Part 6:  引导式提问 → 模糊请求澄清"
echo "   Part 7:  LLM Fallback → 边界情况处理"
echo "   Part 8:  混合技能 → 多技能组合使用"
echo "   Part 9:  引用文本 → referenced_text + action_type"
echo "   Part 10: 文件上传 → 图片/文档/多文件对比"
echo "   Part 11: 引用文本+Skill → referenced_text + quiz/flashcard"
echo "   Part 12: 题目关联 → question_id + answer_id 绑定"
echo "   Part 13: 反馈 API → like/dislike/report"
echo "   Part 14: Token Header → 用户 Token 传递"
echo "   Part 15: 输出格式 → 所有 Skill 输出 text 格式"
echo "   Part 16: files 数组 → 多图片/多文档/混合上传回显"
echo ""
echo "📂 会话记录:"
echo "   Main Session: backend/artifacts/${USER_ID}/${SESSION_ID}.md"
echo "   Question Session: backend/artifacts/${USER_ID}/q${TEST_QID}_a${TEST_AID}.md"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
