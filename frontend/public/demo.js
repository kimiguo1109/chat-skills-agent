// API 配置
const API_BASE = 'http://localhost:8000';
let USER_ID = null;
let SESSION_ID = null;
let CURRENT_USER_DATA = null;

// ============= 用户管理 =============

// 加载可用用户列表
async function loadAvailableUsers() {
    try {
        const response = await fetch(`${API_BASE}/auth/users`);
        const data = await response.json();
        return data.users;
    } catch (error) {
        console.error('Failed to load users:', error);
        return [];
    }
}

// 登录用户
async function loginUser(userId) {
    try {
        const response = await fetch(`${API_BASE}/auth/login`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ user_id: userId })
        });
        
        if (!response.ok) {
            throw new Error('Login failed');
        }
        
        const data = await response.json();
        
        // 更新全局变量
        USER_ID = data.user_id;
        SESSION_ID = data.session_id;
        CURRENT_USER_DATA = {
            user_id: data.user_id,
            username: data.username,
            display_name: data.display_name,
            avatar: data.avatar,
            session_id: data.session_id,
            session_token: data.session_token
        };
        
        // 保存到 localStorage
        localStorage.setItem('session_token', data.session_token);
        localStorage.setItem('current_user', JSON.stringify(CURRENT_USER_DATA));
        
        // 更新UI
        updateCurrentUserDisplay();
        
        console.log(`✅ Logged in as ${data.display_name} (${data.user_id})`);
        return data;
    } catch (error) {
        console.error('Login error:', error);
        alert('Failed to login. Please try again.');
        return null;
    }
}

// 更新当前用户显示
function updateCurrentUserDisplay() {
    if (!CURRENT_USER_DATA) return;
    
    document.getElementById('currentUserAvatar').textContent = CURRENT_USER_DATA.avatar;
    document.getElementById('currentUserName').textContent = CURRENT_USER_DATA.display_name;
    document.getElementById('currentUserSession').textContent = `Session: ${CURRENT_USER_DATA.session_id.split('_')[2]}`;
}

// 显示用户选择器
async function showUserSelector() {
    const modal = document.getElementById('userSelectorModal');
    const container = document.getElementById('userListContainer');
    
    modal.classList.remove('hidden');
    
    // 加载用户列表
    const users = await loadAvailableUsers();
    
    container.innerHTML = users.map(user => `
        <button 
            onclick="selectUser('${user.user_id}')"
            class="flex items-center gap-3 px-4 py-3 rounded-lg hover:bg-primary/10 transition-colors border border-border-light dark:border-border-dark ${user.user_id === USER_ID ? 'bg-primary/5 border-primary' : ''}"
        >
            <span class="text-3xl">${user.avatar}</span>
            <div class="flex flex-col items-start flex-1">
                <p class="text-sm font-bold">${user.display_name}</p>
                <p class="text-xs text-text-light-secondary dark:text-text-dark-secondary">@${user.username}</p>
            </div>
            ${user.user_id === USER_ID ? '<span class="text-xs text-primary font-medium">✓ Current</span>' : ''}
        </button>
    `).join('');
}

// 关闭用户选择器
function closeUserSelector() {
    document.getElementById('userSelectorModal').classList.add('hidden');
}

// 选择用户
async function selectUser(userId) {
    closeUserSelector();
    
    if (userId === USER_ID) {
        console.log('Already logged in as this user');
        return;
    }
    
    // 清空聊天历史
    const chatArea = document.getElementById('chatArea');
    chatArea.innerHTML = '';
    
    // 登录新用户
    await loginUser(userId);
    
    // 添加欢迎消息
    addSystemMessage(`👋 Welcome back, ${CURRENT_USER_DATA.display_name}! How can I help you today?`);
}

// 初始化用户（页面加载时）
async function initializeUser() {
    // 尝试从 localStorage 恢复会话
    const savedToken = localStorage.getItem('session_token');
    const savedUser = localStorage.getItem('current_user');
    
    if (savedToken && savedUser) {
        try {
            CURRENT_USER_DATA = JSON.parse(savedUser);
            USER_ID = CURRENT_USER_DATA.user_id;
            SESSION_ID = CURRENT_USER_DATA.session_id;
            updateCurrentUserDisplay();
            console.log(`✅ Restored session for ${CURRENT_USER_DATA.display_name}`);
            return;
        } catch (error) {
            console.error('Failed to restore session:', error);
        }
    }
    
    // 没有保存的会话，默认登录为 user_kimi
    console.log('No saved session, logging in as default user (user_kimi)');
    await loginUser('user_kimi');
}

// 添加系统消息
function addSystemMessage(message) {
    const chatArea = document.getElementById('chatArea');
    const messageDiv = document.createElement('div');
    messageDiv.className = 'flex gap-4 items-start px-4 py-3 bg-primary/5 rounded-lg';
    messageDiv.innerHTML = `
        <div class="flex flex-col gap-3 flex-1">
            <p class="text-sm">${message}</p>
        </div>
    `;
    chatArea.appendChild(messageDiv);
    chatArea.scrollTop = chatArea.scrollHeight;
}

// 发送消息
// 🌊 流式生成标志（可切换）
const USE_STREAMING = true;  // 设为false使用传统模式

async function handleSend() {
    const input = document.getElementById('messageInput');
    const message = input.value.trim();
    
    if (!message) return;
    
    console.log('📤 Sending message:', message);
    
    // 清空输入框
    input.value = '';
    
    // 添加用户消息
    addUserMessage(message);
    
    if (USE_STREAMING) {
        // 🌊 使用流式API
        await handleStreamingResponse(message);
    } else {
        // 传统模式
        await handleTraditionalResponse(message);
    }
}

// 🌊 流式响应处理
async function handleStreamingResponse(message) {
    // 移除旧的加载消息（如果有）
    removeLoadingMessage();
    
    // 创建流式响应容器
    const responseId = `response-${Date.now()}`;
    createStreamingResponseContainer(responseId);
    
    try {
        const response = await fetch(`${API_BASE}/api/agent/chat-stream`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                user_id: USER_ID,
                session_id: SESSION_ID,
                message: message
            })
        });
        
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        
        while (true) {
            const {done, value} = await reader.read();
            
            if (done) break;
            
            buffer += decoder.decode(value, {stream: true});
            
            // 处理多个事件
            const events = buffer.split('\n\n');
            buffer = events.pop(); // 保留未完成的部分
            
            for (const event of events) {
                if (event.startsWith('data: ')) {
                    try {
                        const data = JSON.parse(event.substring(6));
                        handleStreamChunk(responseId, data);
                    } catch (e) {
                        console.error('JSON parse error:', e);
                    }
                }
            }
        }
        
    } catch (error) {
        console.error('❌ Stream error:', error);
        updateStreamError(responseId, error.message);
    }
}

// 📦 传统响应处理（保留）
async function handleTraditionalResponse(message) {
    addLoadingMessage();
    
    try {
        const response = await fetch(`${API_BASE}/api/agent/chat`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                user_id: USER_ID,
                session_id: SESSION_ID,
                message: message
            })
        });
        
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        
        const data = await response.json();
        console.log('✅ Response data:', data);
        
        removeLoadingMessage();
        addAgentMessage(data);
        
    } catch (error) {
        console.error('❌ Error:', error);
        removeLoadingMessage();
        addErrorMessage(`连接失败: ${error.message}`);
    }
}

// 添加用户消息
function addUserMessage(text) {
    const messagesDiv = document.getElementById('chatMessages').querySelector('.flex.flex-col.gap-6');
    const userMsg = `
        <div class="flex items-end gap-3 justify-end max-w-2xl self-end">
            <div class="flex flex-1 flex-col gap-1 items-end">
                <p class="text-text-light-secondary dark:text-text-dark-secondary text-sm font-medium text-right">User</p>
                <p class="text-base font-normal leading-normal rounded-xl rounded-br-none px-4 py-3 bg-primary text-white">
                    ${text}
                </p>
            </div>
            <div class="bg-center bg-no-repeat aspect-square bg-cover rounded-full size-10 shrink-0" style='background-image: url("https://lh3.googleusercontent.com/aida-public/AB6AXuArOSw_thOdEPdwA2mvCtr7bEwI1o26yboOOAitTWIHYDPmbnNwTq9qItlBoeGCOr1aJjqMhNBQ6lKQ0-FywpKbLhS4HDngJqzdL16mCaOdDxYNZH0_JjfcAVaUUnkUUssz6tNH7d5-jAxm5SCFvP45wXOq1X3Pwznad2FF4YUy9U54XVc4pKeL7dCeWLUku3EEI8Ji5Xlx2TiG0YH8wH2sZucsahOVDTSIK3tjmHeMyEK779v0aYEOc-BEPveggYSTocakuyeLTCgr");'></div>
        </div>
    `;
    messagesDiv.insertAdjacentHTML('beforeend', userMsg);
    scrollToBottom();
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// 🌊 流式响应UI函数
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function createStreamingResponseContainer(responseId) {
    const messagesDiv = document.getElementById('chatMessages').querySelector('.flex.flex-col.gap-6');
    const streamingContainer = `
        <div class="flex items-start gap-3 w-full" id="${responseId}">
            <div class="bg-center bg-no-repeat aspect-square bg-cover rounded-full size-10 shrink-0" style='background-image: url("https://lh3.googleusercontent.com/aida-public/AB6AXuCxe92kEf7gMHjbEHfZQu3F-p4XUO0nyA37zYAuOz7CiVXM_3hgmQ9gTI6zw7siePySKKolumdfXax7FjZ1tuLAnsb5rDYnZjw4LaKpR0MpYWUilv2DSX2VlCD416jAvXmMW3d3TA0MfMgLOkvyyvAqiNcFnqdLIk1LOdKh1Axylm3hUbhf-JtzopMhBhZ5WxEDvTgpGF0E65VLCr805vqY4iosbw4L8Qmm-sViAPSF8dXyszl2XldUnwHCnAakeX7o04PO1S6iwT_m");'></div>
            <div class="flex flex-1 flex-col gap-3 items-start w-full max-w-4xl">
                <p class="text-text-light-secondary dark:text-text-dark-secondary text-sm font-medium">StudyX Agent</p>
                
                <!-- 状态指示器 -->
                <div id="${responseId}-status" class="flex items-center gap-2 text-sm text-text-light-secondary dark:text-text-dark-secondary">
                    <div class="w-2 h-2 rounded-full bg-primary animate-bounce"></div>
                    <span>正在思考...</span>
                </div>
                
                <!-- 🆕 Plan预览区域（最上面，独立显示） -->
                <div id="${responseId}-plan-preview" class="w-full hidden"></div>
                
                <!-- 普通Skill的Thinking Summary（简洁概括，支持多行） -->
                <div id="${responseId}-thinking-overview" class="w-full px-4 py-3 rounded-lg bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 hidden">
                    <div class="flex items-start gap-2">
                        <div class="w-2 h-2 rounded-full bg-blue-500 animate-pulse flex-shrink-0 mt-1"></div>
                        <span class="text-sm italic text-blue-700 dark:text-blue-400 leading-relaxed" id="${responseId}-thinking-overview-text">正在思考...</span>
                    </div>
                </div>
                
                <!-- 普通Skill的完整思考过程区域（可折叠，默认展开） -->
                <div id="${responseId}-thinking-section" class="w-full rounded-xl border border-border-light dark:border-border-dark bg-gray-50 dark:bg-gray-900/50 overflow-hidden hidden">
                    <details class="group" open>
                        <summary class="flex items-center gap-2 px-4 py-3 cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors">
                            <svg class="w-5 h-5 text-primary transition-transform group-open:rotate-90" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"></path>
                            </svg>
                            <span class="text-sm font-semibold text-text-light-primary dark:text-text-dark-primary">💭 完整思考过程</span>
                        </summary>
                        <div class="px-4 py-3 border-t border-border-light dark:border-border-dark max-h-96 overflow-y-auto">
                            <pre id="${responseId}-thinking-content" class="whitespace-pre-wrap text-sm text-text-light-secondary dark:text-text-dark-secondary leading-relaxed"></pre>
                        </div>
                    </details>
                </div>
                
                <!-- 普通Skill的最终结果区域（格式化的卡片UI + 流式生成） -->
                <div id="${responseId}-final" class="w-full hidden"></div>
            </div>
        </div>
    `;
    messagesDiv.insertAdjacentHTML('beforeend', streamingContainer);
    scrollToBottom();
}

// 🐛 记录所有显示过的overview（用于调试）
const thinkingOverviewHistory = new Map(); // responseId -> {overviews: [], fullThinking: ""}

function recordOverviewChange(responseId, overview) {
    if (!thinkingOverviewHistory.has(responseId)) {
        thinkingOverviewHistory.set(responseId, {
            overviews: [],
            fullThinking: '',
            timestamps: []
        });
    }
    
    const history = thinkingOverviewHistory.get(responseId);
    
    // 只记录不同的overview（去重）
    if (history.overviews.length === 0 || history.overviews[history.overviews.length - 1] !== overview) {
        history.overviews.push(overview);
        history.timestamps.push(new Date().toISOString());
        console.log(`[DEBUG] Overview #${history.overviews.length}: ${overview}`);
    }
}

// 🐛 保存Thinking Overview调试数据到后端
async function saveThinkingOverviewDebug(responseId, fullThinking, finalOverview) {
    if (!fullThinking || !finalOverview) {
        console.warn('[DEBUG] Missing thinking or overview, skipping save');
        return;
    }
    
    try {
        // 获取记录的所有overview变化
        const history = thinkingOverviewHistory.get(responseId) || {
            overviews: [finalOverview],
            timestamps: [new Date().toISOString()]
        };
        
        // 更新完整thinking
        history.fullThinking = fullThinking;
        
        // 获取当前的用户查询（从最后一条消息获取）
        const lastUserMessage = document.querySelector('.user-message:last-of-type .prose');
        const userQuery = lastUserMessage ? lastUserMessage.textContent.trim() : '';
        
        const debugData = {
            full_thinking: fullThinking,
            extracted_overview: finalOverview,
            all_overviews: history.overviews,  // 🆕 所有显示过的overview
            overview_timestamps: history.timestamps,  // 🆕 每次变化的时间戳
            timestamp: new Date().toISOString(),
            user_query: userQuery,
            skill_id: responseId
        };
        
        const response = await fetch(`${API_BASE}/api/agent/debug/thinking-overview`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(debugData)
        });
        
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        const result = await response.json();
        console.log(`✅ [DEBUG] Saved thinking overview debug data: Sample #${result.sample_id} (Total: ${result.total_samples})`);
        console.log(`📊 [DEBUG] Recorded ${history.overviews.length} overview changes`);
        
        // 清理历史记录
        thinkingOverviewHistory.delete(responseId);
        
    } catch (error) {
        console.error('[DEBUG] Failed to save thinking overview debug:', error);
    }
}

// 🆕 从thinking文本中提取实际思考内容（智能提取关键信息）
function extractThinkingMotivation(thinkingText) {
    if (!thinkingText) return '🤔 正在思考...';
    
    const length = thinkingText.length;
    
    // 🔥 策略1：提取高价值信息片段（特定模式优先）
    const highValuePatterns = [
        // 用户级别+计划
        {
            pattern: /(new user|新用户)[^.]{0,100}(keep|simple|clear|accessible|基础|简单|清晰)[^.]{0,50}\./gi,
            extract: () => '识别为新用户，准备易懂讲解'
        },
        // 使用比喻
        {
            pattern: /use.*["']([^"']{5,30})["'].*(?:analogy|metaphor|比喻)/gi,
            extract: (match) => {
                const analogyMatch = match.match(/["']([^"']+)["']/);
                if (analogyMatch) return `准备用"${analogyMatch[1]}"作比喻`;
                return '正在设计形象比喻';
            }
        },
        // 计划提供例子
        {
            pattern: /(?:provide|include|need|需要).*?(\d+)[^\d.]{0,10}(?:examples?|例子)/gi,
            extract: (match) => {
                const numMatch = match.match(/(\d+)/);
                if (numMatch) return `计划提供${numMatch[1]}个详细例子`;
                return '正在准备实际例子';
            }
        },
        // 复杂度评估（更细致）
        {
            pattern: /(simple|easy|medium|complex|基础|简单|中等|复杂).*(?:complexity|difficulty|概念)/gi,
            extract: (match) => {
                if (/simple|easy|基础|简单/i.test(match)) return '评估为基础概念';
                if (/medium|moderate|中等/i.test(match)) return '评估为中等难度';
                if (/complex|difficult|复杂/i.test(match)) return '评估为复杂问题';
                return '正在评估难度';
            }
        },
        // Strategy部分的要点
        {
            pattern: /[-•]\s*([A-Z][^.\n]{10,60}(?:example|intuition|definition|analogy|例子|直觉|定义|比喻)[^.\n]{0,40})/gi,
            extract: (match) => {
                const cleaned = match.replace(/^[-•]\s*/, '').trim();
                if (/example/i.test(cleaned)) return '规划具体示例';
                if (/intuition/i.test(cleaned)) return '设计直觉理解';
                if (/definition/i.test(cleaned)) return '准备正式定义';
                if (cleaned.length < 50) return cleaned;
                return '正在规划内容';
            }
        },
        // 即将完成
        {
            pattern: /(looks good|ready|looks complete|完成|准备好)/gi,
            extract: () => '即将完成，准备生成'
        }
    ];
    
    // 尝试高价值模式匹配
    for (const {pattern, extract} of highValuePatterns) {
        const matches = [...thinkingText.matchAll(pattern)];
        if (matches.length > 0) {
            // 优先使用最后一个匹配（最新的思考）
            const lastMatch = matches[matches.length - 1];
            try {
                const result = typeof extract === 'function' ? extract(lastMatch[0]) : extract();
                if (result && result.length > 5 && result.length < 100) {
                    return result;
                }
            } catch (e) {
                console.warn('Extract error:', e);
            }
        }
    }
    
    // 🔥 策略2：提取关键行动句（更通用）
    const actionPatterns = [
        {
            pattern: /(?:I should|I will|I'll|let me|我将|我要)[^.。]{10,80}[.。]/gi,
            transform: (match) => {
                // 提取动词后的关键信息
                const actionMatch = match.match(/(?:provide|explain|use|include|focus|keep|提供|解释|使用|包含|聚焦|保持)\s+([^,.。]{5,40})/i);
                if (actionMatch && actionMatch[1].length < 35) {
                    return `计划：${actionMatch[1].trim()}`;
                }
                return null;
            }
        },
        {
            pattern: /(?:user|新用户|学生).*?(?:is|are|为|是)[^.。]{5,50}(?:new|beginner|basic|初学|基础)/gi,
            transform: () => '识别用户为初学者'
        },
        {
            pattern: /(?:Structure|Format|Construct|构建|组织)[^.。]{10,60}(?:response|JSON|answer|回答|答案)/gi,
            transform: () => '正在组织答案结构'
        }
    ];
    
    for (const {pattern, transform} of actionPatterns) {
        const matches = [...thinkingText.matchAll(pattern)];
        if (matches.length > 0) {
            const lastMatch = matches[matches.length - 1];
            try {
                const result = transform(lastMatch[0]);
                if (result && result.length > 5) {
                    return result;
                }
            } catch (e) {
                console.warn('Transform error:', e);
            }
        }
    }
    
    // 🔥 策略3：提取中文关键句
    const chineseSentences = thinkingText.match(/[\u4e00-\u9fa5][^。！？\n]{12,60}[。！？]/g);
    if (chineseSentences && chineseSentences.length > 0) {
        // 优先选择包含关键词的句子
        const keywordSentence = chineseSentences.find(s => 
            /需要|应该|计划|准备|重点|关键|核心|提供|包含/.test(s)
        );
        if (keywordSentence) {
            let cleaned = keywordSentence.trim().replace(/["「『\(（][^"」』\)）]+["」』\)）]/g, '');
            if (cleaned.length < 80) return cleaned;
        }
        
        // 否则使用最后一个有意义的中文句子
        let lastSentence = chineseSentences[chineseSentences.length - 1].trim();
        lastSentence = lastSentence.replace(/["「『\(（][^"」』\)）]+["」』\)）]/g, '');
        if (lastSentence.length > 10 && lastSentence.length < 80) {
            return lastSentence;
        }
    }
    
    // 🔥 策略4：根据长度和关键词组合推断阶段
    if (length < 300) return '正在理解问题...';
    
    if (length < 1000) {
        if (/strategy|plan|approach|策略|计划|方法/i.test(thinkingText)) return '正在规划回答策略';
        if (/complexity|difficulty|level|复杂|难度|水平/i.test(thinkingText)) return '正在评估问题难度';
        return '正在分析需求...';
    }
    
    if (length < 2500) {
        if (/example|analogy|intuition|例子|比喻|直觉/i.test(thinkingText)) return '正在设计讲解方式';
        if (/structure|format|organize|结构|格式|组织/i.test(thinkingText)) return '正在组织内容结构';
        return '正在规划详细内容...';
    }
    
    if (length < 4500) {
        if (/draft|construct|build|write|起草|构建|编写/i.test(thinkingText)) return '正在起草答案';
        if (/check|verify|ensure|检查|验证|确保/i.test(thinkingText)) return '正在检查内容';
        return '正在完善细节...';
    }
    
    // 接近结束
    if (/ready|complete|good|looks good|完成|准备好|不错/i.test(thinkingText.slice(-500))) {
    return '即将完成...';
}

    return '正在深度思考...';
}

// 🆕 流式渲染辅助函数 - Quiz (与 renderQuizCard 结构对齐)
function renderQuizStreamingUI(partialData) {
    const questions = partialData.questions || [];
    // 外层容器不加 padding/border，因为 renderQuizCard 是每个题目一个卡片
    let html = '<div class="flex flex-col gap-6 w-full">';
    
    questions.forEach((q, idx) => {
        html += `
            <div class="flex flex-col gap-6 rounded-xl border border-border-light dark:border-border-dark bg-surface-light dark:bg-surface-dark p-6 shadow-sm">
                <div class="flex flex-col gap-3">
                    <p class="text-primary text-base font-medium">${partialData.subject || '练习题'}</p>
                    <div class="rounded bg-slate-200 dark:bg-slate-700">
                        <div class="h-2 rounded bg-primary" style="width: ${Math.min(100, ((idx + 1) / (questions.length || 1) * 100))}%;"></div>
                    </div>
                    <p class="text-slate-500 dark:text-slate-400 text-sm">Question ${idx + 1}</p>
                </div>
                <div class="border-t border-border-light dark:border-border-dark"></div>
                <h1 class="text-text-light-primary dark:text-text-dark-primary tracking-tight text-xl font-bold">
                    ${q.question_text || '题目生成中...'}
                    ${!q.question_text ? '<span class="inline-block w-4 h-4 ml-2 rounded-full bg-primary animate-pulse"></span>' : ''}
                </h1>
                
                <div class="flex flex-col gap-3" style="--radio-dot-svg: url('data:image/svg+xml,%3csvg viewBox=%270 0 16 16%27 fill=%27rgb(19,127,236)%27 xmlns=%27http://www.w3.org/2000/svg%27%3e%3ccircle cx=%278%27 cy=%278%27 r=%273%27/%3e%3c/svg%3e');">`;
        
        if (q.options && q.options.length > 0) {
            q.options.forEach((opt, optIdx) => {
                html += `
                    <label class="flex items-center gap-4 rounded-lg border border-solid border-border-light dark:border-border-dark p-4 cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-800/50">
                        <input class="h-5 w-5 border-2 border-border-light dark:border-border-dark bg-transparent text-transparent checked:border-primary checked:bg-[image:--radio-dot-svg] focus:outline-none focus:ring-0" name="quiz_stream_${idx}" type="radio" disabled/>
                        <div class="flex grow flex-col"><p class="text-text-light-primary dark:text-text-dark-primary text-sm font-medium">${opt}</p></div>
                    </label>`;
            });
        } else {
            // 占位符选项
            html += `<div class="animate-pulse h-12 bg-slate-100 dark:bg-slate-800 rounded-lg"></div>`;
            html += `<div class="animate-pulse h-12 bg-slate-100 dark:bg-slate-800 rounded-lg"></div>`;
        }
        
        html += `</div>`; // End options container
        html += `</div>`; // End card
    });
    
    if (questions.length === 0) {
        html += `
            <div class="flex flex-col gap-6 rounded-xl border border-border-light dark:border-border-dark bg-surface-light dark:bg-surface-dark p-6 shadow-sm">
                <div class="animate-pulse flex flex-col gap-4">
                    <div class="h-4 bg-slate-200 dark:bg-slate-700 rounded w-1/4"></div>
                    <div class="h-8 bg-slate-200 dark:bg-slate-700 rounded w-3/4"></div>
                    <div class="space-y-3">
                        <div class="h-12 bg-slate-200 dark:bg-slate-700 rounded"></div>
                        <div class="h-12 bg-slate-200 dark:bg-slate-700 rounded"></div>
                    </div>
                </div>
                <div class="text-center text-blue-500 animate-pulse mt-2">正在设计题目...</div>
            </div>`;
    }
    
    html += '</div>';
    return html;
}

// 🆕 流式渲染辅助函数 - Flashcard (与 renderFlashcardSet 结构对齐)
function renderFlashcardStreamingUI(partialData) {
    const cards = partialData.cards || [];
    let html = '<div class="flex flex-col gap-4 w-full">';
    html += `<h3 class="text-lg font-bold text-text-light-primary dark:text-text-dark-primary">📚 抽认卡集合</h3>`;
    
    cards.forEach((card, idx) => {
        html += `
            <div class="rounded-xl border border-border-light dark:border-border-dark bg-surface-light dark:bg-surface-dark p-6 shadow-sm">
                <div class="flex items-center gap-2 mb-4">
                    <span class="bg-primary text-white rounded-full h-6 w-6 inline-flex items-center justify-center text-sm">${idx + 1}</span>
                    <span class="text-sm text-slate-500">${card.card_type || 'generating...'}</span>
                </div>
                <div class="space-y-4">
                    <div>
                        <p class="text-sm font-medium text-slate-500 mb-2">正面（Front）</p>
                        <p class="text-base text-text-light-primary dark:text-text-dark-primary">
                            ${card.front || '生成中...'}
                            ${!card.front ? '<span class="inline-block w-2 h-2 ml-1 rounded-full bg-slate-400 animate-pulse"></span>' : ''}
                        </p>
                    </div>
                    <div class="border-t border-border-light dark:border-border-dark pt-4">
                        <p class="text-sm font-medium text-slate-500 mb-2">背面（Back）</p>
                        <p class="text-base text-text-light-primary dark:text-text-dark-primary">${card.back || ''}</p>
                    </div>`;
        
        if (card.hints && card.hints.length > 0) {
            html += `
                    <div class="bg-slate-50 dark:bg-slate-800/50 p-3 rounded-lg">
                        <p class="text-sm font-medium text-primary mb-1">💡 提示</p>
                        <ul class="text-sm text-slate-600 dark:text-slate-300 list-disc list-inside">
                            ${card.hints.map(h => `<li>${h}</li>`).join('')}
                        </ul>
                    </div>`;
        }
        
        html += `</div></div>`;
    });
    
    if (cards.length === 0) {
        html += `
            <div class="rounded-xl border border-border-light dark:border-border-dark bg-surface-light dark:bg-surface-dark p-6 shadow-sm">
                <div class="animate-pulse space-y-4">
                    <div class="h-6 bg-slate-200 dark:bg-slate-700 rounded w-1/4"></div>
                    <div class="space-y-2">
                        <div class="h-4 bg-slate-200 dark:bg-slate-700 rounded w-1/6"></div>
                        <div class="h-16 bg-slate-200 dark:bg-slate-700 rounded"></div>
                    </div>
                </div>
                <div class="text-center text-blue-500 animate-pulse mt-4">正在绘制卡片...</div>
            </div>`;
    }
    
    html += '</div>';
    return html;
}

// 🆕 流式渲染辅助函数 - Notes (与 renderNotesCard 结构对齐)
function renderNotesStreamingUI(partialData) {
    const notes = partialData.structured_notes || {};
    const sections = notes.sections || [];
    // 使用临时ID，流式过程中不绑定事件
    const notesId = 'streaming_notes';
    
    let html = `
        <div class="w-full rounded-xl border-2 border-border-light dark:border-border-dark bg-white dark:bg-gray-800 shadow-lg overflow-hidden notebook-container">
            <!-- 笔记头部 -->
            <div class="bg-gradient-to-r from-blue-500 to-purple-600 p-6">
                <div class="flex items-center justify-between">
                    <div class="flex items-center gap-3">
                        <span class="material-symbols-outlined text-white text-3xl">description</span>
                        <div>
                            <p class="text-sm text-blue-100">${partialData.subject || '学习笔记'}</p>
                            <h3 class="text-2xl font-bold text-white">
                                ${notes.title || partialData.topic || '笔记生成中...'}
                                ${!notes.title ? '<span class="inline-block w-3 h-3 ml-2 rounded-full bg-white/50 animate-pulse"></span>' : ''}
                            </h3>
                        </div>
                    </div>
                    <!-- 流式状态下不显示编辑按钮 -->
                    <div class="px-3 py-1 bg-white/20 rounded-full text-white text-xs flex items-center gap-1">
                        <span class="w-2 h-2 bg-green-400 rounded-full animate-pulse"></span>
                        Writing...
                    </div>
                </div>
            </div>
            
            <!-- 笔记内容区域 -->
            <div class="p-8 space-y-6 notes-content bg-amber-50/30 dark:bg-gray-900/30">`;
    
    if (sections.length > 0) {
        sections.forEach((section, idx) => {
            html += `
                <div class="notebook-section bg-white dark:bg-gray-800 rounded-lg p-6 border-l-4 border-blue-500 shadow-sm">
                    <div class="flex items-center justify-between mb-4">
                        <h4 class="text-xl font-bold text-gray-800 dark:text-gray-100 section-heading">
                            ${section.heading || '章节生成中...'}
                        </h4>
                    </div>
                    <ul class="space-y-3 bullet-list">`;
    
            if (section.bullet_points && section.bullet_points.length > 0) {
                section.bullet_points.forEach((point) => {
                    html += `
                        <li class="flex gap-3 group">
                            <span class="mt-1.5 w-2 h-2 rounded-full bg-blue-400 flex-shrink-0"></span>
                            <span class="text-gray-700 dark:text-gray-300 leading-relaxed">${point}</span>
                        </li>`;
                });
            } else {
                html += `<li class="animate-pulse h-4 bg-slate-100 dark:bg-slate-700 rounded w-3/4 ml-5"></li>`;
            }
            
            html += `   </ul>
                </div>`;
        });
    } else {
        html += `
            <div class="notebook-section bg-white dark:bg-gray-800 rounded-lg p-6 border-l-4 border-slate-300 shadow-sm opacity-70">
                <div class="animate-pulse space-y-4">
                    <div class="h-6 bg-slate-200 dark:bg-slate-700 rounded w-1/3"></div>
                    <div class="space-y-2 pl-4">
                        <div class="h-4 bg-slate-200 dark:bg-slate-700 rounded w-3/4"></div>
                        <div class="h-4 bg-slate-200 dark:bg-slate-700 rounded w-5/6"></div>
                        <div class="h-4 bg-slate-200 dark:bg-slate-700 rounded w-2/3"></div>
                    </div>
                </div>
            </div>`;
    }
    
    html += `   </div>
        </div>`;
        
    return html;
}

function renderExplanationStreamingUI(partialData) {
    // 🔥 复刻 renderExplainCard 的结构，确保流式到最终结果的无缝过渡
    const concept = partialData.concept || '正在生成...';
    const intuition = partialData.intuition || '';
    const formalDef = partialData.formal_definition || '';
    const examples = partialData.examples || [];
    
    let html = `
        <div class="w-full rounded-xl border border-border-light dark:border-border-dark bg-surface-light dark:bg-surface-dark shadow-sm">
            <div class="p-6">
                <h1 class="text-2xl font-bold text-text-light-primary dark:text-text-dark-primary tracking-tight">
                    ${concept}
                    ${!partialData.concept ? '<span class="inline-block w-4 h-4 ml-2 rounded-full bg-primary animate-pulse"></span>' : ''}
                </h1>
            </div>
            <div class="px-6 pb-6 text-base text-text-light-primary dark:text-text-dark-primary space-y-4">
                <p>${intuition}</p>`;
    
    if (formalDef) {
        html += `
                <div class="my-4 p-4 bg-background-light dark:bg-background-dark rounded-lg font-mono text-sm">
                    <span class="font-bold">${formalDef}</span>
                </div>`;
    }
    
    if (examples && examples.length > 0) {
        html += `
            </div>
            <hr class="border-border-light dark:border-border-dark"/>
            <div class="p-6">
                <h2 class="text-xl font-semibold text-text-light-primary dark:text-text-dark-primary mb-5">例子</h2>
                <div class="space-y-6">`;
        
        examples.forEach((ex, idx) => {
            html += `
                    <div class="flex flex-col gap-3">
                        <h3 class="font-semibold text-text-light-primary dark:text-text-dark-primary">
                            <span class="bg-primary text-white rounded-full h-6 w-6 inline-flex items-center justify-center text-sm mr-2">${idx + 1}</span>
                            ${ex.example || ex.title || '生成中...'}
                        </h3>
                        <div class="pl-8 text-slate-600 dark:text-slate-300 border-l-2 border-primary/50 ml-3">
                            <p>${ex.explanation || ''}</p>
                        </div>
                    </div>`;
        });
        
        html += `</div>`;
    } else {
        // 如果没有例子，闭合上面的 div
        html += `</div>`;
    }
    
    // 如果内容很少，显示加载动画
    if (!partialData.intuition && !partialData.formal_definition) {
        html += `
            <div class="px-6 pb-6">
                <div class="flex items-center gap-2 text-blue-500 animate-pulse">
                    <span class="material-symbols-outlined text-xl">edit_note</span>
                    <span>正在撰写直观解释...</span>
                </div>
            </div>`;
    }
    
    html += `</div>`;
    return html;
}

function handleStreamChunk(responseId, data) {
    // ✅ 流式输出已验证正常工作！所有Stream日志已注释以减少console噪音
    // 如需调试，可临时启用下面的日志
    // if (!['thinking', 'content'].includes(data.type)) {
    //     console.log('[Stream]', data.type, data);
    // }
    
    const statusEl = document.getElementById(`${responseId}-status`);
    const planPreviewEl = document.getElementById(`${responseId}-plan-preview`);
    const thinkingSection = document.getElementById(`${responseId}-thinking-section`);
    const thinkingEl = document.getElementById(`${responseId}-thinking-content`);
    const contentSection = document.getElementById(`${responseId}-content-section`);
    const contentTextEl = document.getElementById(`${responseId}-content-text`);
    const finalEl = document.getElementById(`${responseId}-final`);
    
    if (data.type === 'status') {
        if (statusEl) {
            statusEl.querySelector('span').textContent = data.message;
        }
    }
    // 🆕 Plan Skill进度事件
    else if (data.type === 'plan_start') {
        if (statusEl) {
            statusEl.querySelector('span').textContent = `🎓 生成学习包：${data.topic} (${data.total_steps}个步骤)`;
        }
        
        // 🆕 渲染Plan Preview卡片（在专用区域）
        if (data.steps_preview && data.steps_preview.length > 0 && planPreviewEl) {
            const previewHtml = renderPlanPreview(data.topic, data.steps_preview, data.total_steps);
            planPreviewEl.innerHTML = previewHtml;
            planPreviewEl.classList.remove('hidden'); // 🔧 显示预览卡片！
            
            // 🆕 2秒后隐藏Planning阶段提示
            setTimeout(() => {
                const planningPhase = document.getElementById('plan-planning-phase');
                if (planningPhase) {
                    planningPhase.style.display = 'none';
                }
            }, 2000);
            
            scrollToBottom();
        }
    }
    else if (data.type === 'step_start') {
        // 更新状态显示当前步骤
        if (statusEl) {
            statusEl.querySelector('span').textContent = `📍 Step ${data.step_order}/${data.total_steps}: ${data.step_name}`;
        }
        
        // 🆕 更新Task Progress计数器
        const progressCurrent = document.getElementById('plan-progress-current');
        if (progressCurrent) {
            progressCurrent.textContent = data.step_order - 1; // 显示已完成的步骤数
        }
        
        // 🆕 更新Plan Preview中的进度指示器
        const stepIndicator = document.getElementById(`plan-step-${data.step_order}`);
        if (stepIndicator) {
            // 移除所有步骤的active状态和隐藏live thinking
            document.querySelectorAll('.plan-step-item').forEach(el => {
                el.classList.remove('border-primary', 'bg-blue-50', 'dark:bg-blue-900/20');
                el.classList.add('border-border-light', 'dark:border-border-dark');
                // 隐藏其他步骤的live thinking
                const otherLiveThinking = el.querySelector('[id$="-live-thinking"]');
                if (otherLiveThinking) {
                    otherLiveThinking.classList.add('hidden');
                }
            });
            
            // 标记当前步骤为进行中
            stepIndicator.classList.remove('border-border-light', 'dark:border-border-dark');
            stepIndicator.classList.add('border-primary', 'bg-blue-50', 'dark:bg-blue-900/20');
            
            // 更新步骤状态图标
            const statusIcon = stepIndicator.querySelector('.step-status-icon');
            if (statusIcon) {
                statusIcon.textContent = '⏳';
            }
            
            // 更新步骤状态标签
            const statusLabel = stepIndicator.querySelector('.step-status-label');
            if (statusLabel) {
                statusLabel.textContent = 'Thinking';
                statusLabel.classList.remove('bg-gray-100', 'dark:bg-gray-800', 'text-text-light-secondary', 'dark:text-text-dark-secondary');
                statusLabel.classList.add('bg-blue-100', 'dark:bg-blue-900', 'text-blue-700', 'dark:text-blue-300');
            }
            
            // 显示thinking summary（简洁概括）
            const thinkingSummary = document.getElementById(`plan-step-${data.step_order}-thinking-summary`);
            if (thinkingSummary) {
                thinkingSummary.classList.remove('hidden');
                // 设置默认的thinking状态文字
                const summaryText = thinkingSummary.querySelector('.thinking-summary-text');
                if (summaryText) {
                    summaryText.textContent = `正在${data.step_name}...`;
                }
            }
            
            // 显示完整thinking区域（可折叠）
            const thinkingFull = document.getElementById(`plan-step-${data.step_order}-thinking-full`);
            if (thinkingFull) {
                thinkingFull.classList.remove('hidden');
            }
            
            // 显示时间追踪
            const timeTracker = stepIndicator.querySelector('.step-time-tracker');
            if (timeTracker) {
                timeTracker.classList.remove('hidden');
                // 开始计时
                const startTime = Date.now();
                const timerInterval = setInterval(() => {
                    const elapsed = Math.floor((Date.now() - startTime) / 1000);
                    const minutes = Math.floor(elapsed / 60);
                    const seconds = elapsed % 60;
                    const timeEl = timeTracker.querySelector('.step-elapsed-time');
                    if (timeEl) {
                        timeEl.textContent = `${minutes}:${seconds.toString().padStart(2, '0')}`;
                    }
                }, 1000);
                // 存储timer以便后续清除
                stepIndicator.dataset.timerInterval = timerInterval;
            }
            
            // 🆕 显示该步骤的thinking容器
            const stepThinkingContainer = document.getElementById(`plan-step-${data.step_order}-thinking-container`);
            if (stepThinkingContainer) {
                stepThinkingContainer.classList.remove('hidden');
            }
        }
    }
    else if (data.type === 'step_done') {
        // 步骤完成，可以添加完成标记
        if (statusEl) {
            statusEl.querySelector('span').textContent = `✅ Step ${data.step_order}/${data.total_steps} 完成`;
        }
        
        // 🆕 更新Task Progress计数器
        const progressCurrent = document.getElementById('plan-progress-current');
        if (progressCurrent) {
            progressCurrent.textContent = data.step_order;
        }
        
        // 🆕 更新Plan Preview中的完成状态
        const stepIndicator = document.getElementById(`plan-step-${data.step_order}`);
        if (stepIndicator) {
            // 停止计时
            if (stepIndicator.dataset.timerInterval) {
                clearInterval(parseInt(stepIndicator.dataset.timerInterval));
            }
            
            // 标记为已完成
            stepIndicator.classList.remove('border-primary', 'bg-blue-50', 'dark:bg-blue-900/20');
            stepIndicator.classList.add('border-green-500', 'bg-green-50', 'dark:bg-green-900/20');
            
            // 更新步骤状态图标
            const statusIcon = stepIndicator.querySelector('.step-status-icon');
            if (statusIcon) {
                statusIcon.textContent = '✅';
            }
            
            // 更新步骤状态标签
            const statusLabel = stepIndicator.querySelector('.step-status-label');
            if (statusLabel) {
                statusLabel.textContent = '完成';
                statusLabel.classList.remove('bg-blue-100', 'dark:bg-blue-900', 'text-blue-700', 'dark:text-blue-300');
                statusLabel.classList.add('bg-green-100', 'dark:bg-green-900', 'text-green-700', 'dark:text-green-300');
            }
            
            // 🔥 步骤完成后隐藏thinking summary（用户只想在thinking过程中看到）
            const thinkingSummary = document.getElementById(`plan-step-${data.step_order}-thinking-summary`);
            if (thinkingSummary) {
                thinkingSummary.classList.add('hidden');
                
                // 🐛 保存Debug数据（如果有reasoning_summary）
                if (data.result && data.result.reasoning_summary) {
                    console.log(`[DEBUG] Plan Step ${data.step_order} reasoning_summary:`, data.result.reasoning_summary);
                }
            }
            
            // 🆕 立即在该步骤下方显示输出结果
            const stepOutputSection = document.getElementById(`plan-step-${data.step_order}-output`);
            const stepOutputContent = document.getElementById(`plan-step-${data.step_order}-output-content`);
            
            console.log(`[DEBUG] step_done event - step ${data.step_order}`);
            console.log(`[DEBUG] data.result:`, data.result);
            console.log(`[DEBUG] stepOutputSection:`, stepOutputSection);
            console.log(`[DEBUG] stepOutputContent:`, stepOutputContent);
            
            if (stepOutputSection && stepOutputContent && data.result) {
                stepOutputSection.classList.remove('hidden');
                
                // 根据result的类型渲染不同的UI
                const result = data.result;
                const contentType = detectContentType(result);
                
                // DEBUG 日志已注释
                // console.log(`[DEBUG] detected contentType:`, contentType);
                // console.log(`[DEBUG] result.concept:`, result.concept);
                // console.log(`[DEBUG] result.cards:`, result.cards);
                // console.log(`[DEBUG] result.questions:`, result.questions);
                
                if (contentType === 'explanation' && result.concept) {
                    // console.log(`[DEBUG] Rendering explanation card`);
                    stepOutputContent.innerHTML = renderExplainCard(result);
                } else if (contentType === 'flashcard_set' && result.cards) {
                    // console.log(`[DEBUG] Rendering flashcard set`);
                    stepOutputContent.innerHTML = renderFlashcardSet(result);
                } else if (contentType === 'quiz_set' && result.questions) {
                    // console.log(`[DEBUG] Rendering quiz card`);
                    stepOutputContent.innerHTML = renderQuizCard(result);
                } else if (contentType === 'mindmap' && result.root) {
                    stepOutputContent.innerHTML = renderMindMapCard(result);
                } else if (contentType === 'notes' && result.structured_notes) {
                    stepOutputContent.innerHTML = renderNotesCard(result);
                } else {
                    // 未知类型，显示简单的JSON摘要
                    // console.log(`[DEBUG] Unknown type, showing raw JSON`);
                    stepOutputContent.innerHTML = `
                        <div class="text-sm text-text-light-secondary dark:text-text-dark-secondary">
                            <p class="font-semibold mb-2">步骤结果：</p>
                            <pre class="text-xs bg-white dark:bg-gray-800 p-3 rounded border border-border-light dark:border-border-dark overflow-auto max-h-64">${JSON.stringify(result, null, 2)}</pre>
                        </div>
                    `;
                }
            } else {
                console.warn(`[DEBUG] Missing elements or result:`, {
                    stepOutputSection: !!stepOutputSection,
                    stepOutputContent: !!stepOutputContent,
                    hasResult: !!data.result
                });
            }
        }
    }
    else if (data.type === 'step_error') {
        // 步骤失败
        if (statusEl) {
            statusEl.querySelector('span').textContent = `⚠️ Step ${data.step_order} 失败: ${data.error}`;
        }
        
        // 🆕 更新Plan Preview中的错误状态
        const stepIndicator = document.getElementById(`plan-step-${data.step_order}`);
        if (stepIndicator) {
            // 标记为失败
            stepIndicator.classList.remove('border-primary', 'bg-blue-50', 'dark:bg-blue-900/20');
            stepIndicator.classList.add('border-red-500', 'bg-red-50', 'dark:bg-red-900/20');
            
            // 更新步骤状态图标
            const statusIcon = stepIndicator.querySelector('.step-status-icon');
            if (statusIcon) {
                statusIcon.textContent = '❌';
            }
        }
    } 
    else if (data.type === 'thinking') {
        // 检测是否是Plan Skill（通过status文本判断）
        const statusText = statusEl?.querySelector('span')?.textContent || '';
        const isPlanSkill = statusText.includes('Step') && statusText.includes('/');
        const stepMatch = statusText.match(/Step (\d+)\//);
        const currentStep = stepMatch ? parseInt(stepMatch[1]) : null;
        
        if (isPlanSkill && currentStep) {
            // Plan Skill：更新完整thinking内容（流式显示）
            const stepThinkingContent = document.getElementById(`plan-step-${currentStep}-thinking-content`);
            if (stepThinkingContent) {
                // 累积文本
                stepThinkingContent.textContent += data.text;
                
                // 简单的Markdown渲染：**粗体**
                let renderedText = stepThinkingContent.textContent
                    .replace(/\*\*(.*?)\*\*/g, '<strong class="font-semibold text-text-light-primary dark:text-text-dark-primary">$1</strong>');
                
                stepThinkingContent.innerHTML = renderedText;
                
                // LaTeX渲染（KaTeX）
                if (typeof renderMathInElement !== 'undefined') {
                    try {
                        renderMathInElement(stepThinkingContent, {
                            delimiters: [
                                {left: '$$', right: '$$', display: true},
                                {left: '$', right: '$', display: false},
                                {left: '\\[', right: '\\]', display: true},
                                {left: '\\(', right: '\\)', display: false}
                            ],
                            throwOnError: false
                        });
                    } catch (e) {
                        console.warn('LaTeX rendering error:', e);
                    }
                }
            }
            
            // 🔥 Plan Skill也动态提取thinking动机
            const thinkingSummary = document.getElementById(`plan-step-${currentStep}-thinking-summary`);
            if (thinkingSummary) {
                const summaryText = thinkingSummary.querySelector('.thinking-summary-text');
                if (summaryText && stepThinkingContent) {
                    const fullText = stepThinkingContent.textContent;
                    
                    // 检测thinking即将结束的关键词
                    const thinkingEndKeywords = [
                        'Let me craft the JSON',
                        'craft the JSON response',
                        'following the exact format',
                        '按照要求的格式',
                        '现在开始生成JSON',
                        '现在生成JSON'
                    ];
                    const isThinkingEnding = thinkingEndKeywords.some(kw => fullText.includes(kw));
                    
                    if (isThinkingEnding && !summaryText.textContent.includes('准备生成')) {
                        // 过渡阶段
                        const transitionText = '⏳ 准备生成内容...';
                        summaryText.textContent = transitionText;
                        recordOverviewChange(responseId, transitionText);
                        
                        const pulseIcon = thinkingSummary.querySelector('.animate-pulse');
                        if (pulseIcon) {
                            pulseIcon.classList.remove('bg-blue-500');
                            pulseIcon.classList.add('bg-yellow-500');
                        }
                    } else if (!isThinkingEnding) {
                        // 🔥 动态提取思考动机（优化：更频繁地检查，捕捉更多思考阶段）
                        const shouldUpdate = fullText.length % 80 < 5 || /[.。!！?？]/.test(data.text);
                        if (shouldUpdate) {
                            const motivation = extractThinkingMotivation(fullText);
                            if (motivation && summaryText.textContent !== motivation) {
                                summaryText.textContent = motivation;
                                recordOverviewChange(responseId, motivation);
                            }
                        }
                    }
                }
            }
        } else {
            // 普通Skill：显示完整thinking内容（流式）
            if (thinkingSection && thinkingSection.classList.contains('hidden')) {
                thinkingSection.classList.remove('hidden');
            }
            if (thinkingEl) {
                // 累积文本并渲染Markdown + LaTeX
                thinkingEl.textContent += data.text;
                
                // 简单的Markdown渲染：**粗体**
                let renderedText = thinkingEl.textContent
                    .replace(/\*\*(.*?)\*\*/g, '<strong class="font-semibold text-text-light-primary dark:text-text-dark-primary">$1</strong>');
                
                thinkingEl.innerHTML = renderedText;
                
                // LaTeX渲染（KaTeX）
                if (typeof renderMathInElement !== 'undefined') {
                    try {
                        renderMathInElement(thinkingEl, {
                            delimiters: [
                                {left: '$$', right: '$$', display: true},
                                {left: '$', right: '$', display: false},
                                {left: '\\[', right: '\\]', display: true},
                                {left: '\\(', right: '\\)', display: false}
                            ],
                            throwOnError: false
                        });
                    } catch (e) {
                        console.warn('LaTeX rendering error:', e);
                    }
                }
            }
            
            // 🆕 智能提取thinking summary（降低更新频率，减少跳动）
            const thinkingOverview = document.getElementById(`${responseId}-thinking-overview`);
            if (thinkingOverview) {
                if (thinkingOverview.classList.contains('hidden')) {
                    thinkingOverview.classList.remove('hidden');
                }
                const overviewText = document.getElementById(`${responseId}-thinking-overview-text`);
                if (overviewText && thinkingEl) {
                    const fullText = thinkingEl.textContent;
                    
                    // 🔥 检测thinking即将结束的关键词
                    const thinkingEndKeywords = [
                        'Let me craft the JSON',
                        'craft the JSON response',
                        'following the exact format',
                        '按照要求的格式',
                        '现在开始生成JSON',
                        'Now let me generate'
                    ];
                    const isThinkingEnding = thinkingEndKeywords.some(kw => fullText.includes(kw));
                    
                    if (isThinkingEnding && !overviewText.textContent.includes('准备生成')) {
                        // 🎨 thinking即将结束，显示明显提示
                        const transitionText = '⏳ 准备生成内容...';
                        overviewText.innerHTML = `<span class="animate-pulse">${transitionText}</span>`;
                        // 🐛 记录过渡阶段的overview
                        recordOverviewChange(responseId, transitionText);
                        
                        const pulseIcon = thinkingOverview.querySelector('.w-2.h-2');
                        if (pulseIcon) {
                            pulseIcon.classList.remove('bg-blue-500');
                            pulseIcon.classList.add('bg-yellow-500');
                        }
                        thinkingOverview.style.backgroundColor = 'rgba(251, 191, 36, 0.1)';
                    } else if (!isThinkingEnding) {
                        // 🔥 从thinking内容中提取思考动机和计划（优化：更频繁地检查）
                        const shouldUpdate = fullText.length % 80 < 5 || /[.。!！?？]/.test(data.text);
                        if (shouldUpdate) {
                            const motivation = extractThinkingMotivation(fullText);
                            if (motivation && overviewText.textContent !== motivation) {
                                overviewText.textContent = motivation;
                                // 🐛 记录overview变化
                                recordOverviewChange(responseId, motivation);
                            }
                        }
                    }
                }
            }
        }
        
        scrollToBottom();
    } 
    else if (data.type === 'content') {
        // 🔥 流式显示实际内容（quiz、flashcard等）
        const statusText = statusEl?.querySelector('span')?.textContent || '';
        const isPlanSkill = statusText.includes('Step') && statusText.includes('/');
        const stepMatch = statusText.match(/Step (\d+)\//);
        const currentStep = stepMatch ? parseInt(stepMatch[1]) : null;
        
        // 统计累计字符数
        const contentLength = data.accumulated ? data.accumulated.length : 0;
        
        // 🔥 实时解析并显示内容片段
        let previewHTML = '';
        if (data.accumulated && contentLength > 100) {
            try {
                // 尝试提取quiz题目、flashcard等
                const quizMatch = data.accumulated.match(/"question_text":\s*"([^"]+)"/g);
                const flashcardMatch = data.accumulated.match(/"front":\s*"([^"]+)"/g);
                const conceptMatch = data.accumulated.match(/"concept":\s*"([^"]+)"/);
                const intuitionMatch = data.accumulated.match(/"intuition":\s*"([^"]+)"/);
                
                if (quizMatch) {
                    // Quiz题目流式显示
                    previewHTML = '<div class="space-y-2">';
                    quizMatch.slice(0, 3).forEach((match, idx) => {
                        const question = match.match(/"question_text":\s*"([^"]+)"/)[1];
                        previewHTML += `<div class="text-sm"><strong>题目${idx+1}:</strong> ${question}</div>`;
                    });
                    if (quizMatch.length > 3) {
                        previewHTML += `<div class="text-xs text-gray-500">... 共${quizMatch.length}道题</div>`;
                    }
                    previewHTML += '</div>';
                } else if (flashcardMatch) {
                    // Flashcard流式显示
                    previewHTML = '<div class="space-y-2">';
                    flashcardMatch.slice(0, 3).forEach((match, idx) => {
                        const front = match.match(/"front":\s*"([^"]+)"/)[1];
                        previewHTML += `<div class="text-sm"><strong>卡片${idx+1}:</strong> ${front}</div>`;
                    });
                    if (flashcardMatch.length > 3) {
                        previewHTML += `<div class="text-xs text-gray-500">... 共${flashcardMatch.length}张卡片</div>`;
                    }
                    previewHTML += '</div>';
                } else if (conceptMatch || intuitionMatch) {
                    // Explanation流式显示
                    previewHTML = '<div class="space-y-1 text-sm">';
                    if (conceptMatch) {
                        previewHTML += `<div><strong>概念:</strong> ${conceptMatch[1]}</div>`;
                    }
                    if (intuitionMatch) {
                        const intuition = intuitionMatch[1].slice(0, 100);
                        previewHTML += `<div><strong>直觉:</strong> ${intuition}...</div>`;
                    }
                    previewHTML += '</div>';
                }
            } catch (e) {
                console.warn('Content preview parse error:', e);
            }
        }
        
        // 更新content流式渲染
        if (isPlanSkill && currentStep) {
            // Plan Skill：在步骤的output区域流式渲染内容
            const stepOutputContent = document.getElementById(`plan-step-${currentStep}-output-content`);
            
            if (stepOutputContent) {
                // 显示output容器
                const stepOutput = document.getElementById(`plan-step-${currentStep}-output`);
                if (stepOutput) {
                    stepOutput.classList.remove('hidden');
                }
                
                // 流式渲染内容
                try {
                    const partialData = JSON.parse(data.accumulated);
                    
                    if (partialData.questions && Array.isArray(partialData.questions)) {
                        stepOutputContent.innerHTML = renderQuizStreamingUI(partialData);
                    } else if (partialData.cards && Array.isArray(partialData.cards)) {
                        stepOutputContent.innerHTML = renderFlashcardStreamingUI(partialData);
                    } else if (partialData.concept) {
                        stepOutputContent.innerHTML = renderExplanationStreamingUI(partialData);
                    } else if (partialData.structured_notes) {
                        stepOutputContent.innerHTML = renderNotesStreamingUI(partialData);
                    }
                } catch (e) {
                    // 🔥 JSON不完整，使用正则智能提取
                    const acc = data.accumulated || '';
                    
                    const extract = (key) => {
                        const regex = new RegExp(`"${key}"\\s*:\\s*"((?:[^"\\\\]|\\\\.)*)`);
                        const match = acc.match(regex);
                        return match ? match[1] : null;
                    };

                    const partialData = {
                        concept: extract('concept'),
                        intuition: extract('intuition'),
                        formal_definition: extract('formal_definition'),
                        questions: [],
                        cards: [],
                        examples: [],  // 🆕 添加 examples 数组
                        structured_notes: {
                            title: extract('title'),
                            sections: []
                        }
                    };
                    
                    // 提取数组项
                    const questionMatches = acc.matchAll(/"question_text"\s*:\s*"((?:[^"\\\\]|\\\\.)*)/g);
                    for (const m of questionMatches) partialData.questions.push({ question_text: m[1] });
                    
                    const cardMatches = acc.matchAll(/"front"\s*:\s*"((?:[^"\\\\]|\\\\.)*)/g);
                    for (const m of cardMatches) partialData.cards.push({ front: m[1] });

                    // 🆕 提取 examples（example 和 explanation 字段）
                    const examplePattern = /"example"\s*:\s*"((?:[^"\\\\]|\\.)*)"/g;
                    const explanationPattern = /"explanation"\s*:\s*"((?:[^"\\\\]|\\.)*)"/g;
                    const exampleMatches = [...acc.matchAll(examplePattern)];
                    const explanationMatches = [...acc.matchAll(explanationPattern)];
                    
                    // 组合 example 和对应的 explanation
                    for (let i = 0; i < Math.max(exampleMatches.length, explanationMatches.length); i++) {
                        partialData.examples.push({
                            example: exampleMatches[i] ? exampleMatches[i][1] : '生成中...',
                            explanation: explanationMatches[i] ? explanationMatches[i][1] : ''
                        });
                    }

                    const sectionMatches = acc.matchAll(/"heading"\s*:\s*"((?:[^"\\\\]|\\\\.)*)/g);
                    for (const m of sectionMatches) partialData.structured_notes.sections.push({ heading: m[1], points: [] });

                    if (partialData.questions.length > 0) {
                        stepOutputContent.innerHTML = renderQuizStreamingUI(partialData);
                    } else if (partialData.cards.length > 0) {
                        stepOutputContent.innerHTML = renderFlashcardStreamingUI(partialData);
                    } else if (partialData.concept || partialData.intuition) {
                        stepOutputContent.innerHTML = renderExplanationStreamingUI(partialData);
                    } else if (partialData.structured_notes.title || partialData.structured_notes.sections.length > 0) {
                        stepOutputContent.innerHTML = renderNotesStreamingUI(partialData);
                    } else {
                    if (!stepOutputContent.innerHTML) {
                        stepOutputContent.innerHTML = '<div class="text-center py-4"><div class="animate-pulse text-blue-500">📝 正在生成内容...</div></div>';
                        }
                    }
                }
            } else {
                console.error(`[DEBUG] stepOutputContent not found for step ${currentStep}`);
            }
            
            // 更新thinking summary为"正在生成内容..."
            const thinkingSummary = document.getElementById(`plan-step-${currentStep}-thinking-summary`);
            if (thinkingSummary) {
                const summaryText = thinkingSummary.querySelector('.thinking-summary-text');
                if (summaryText && !summaryText.textContent.includes('正在生成')) {
                    summaryText.textContent = '📝 正在生成内容...';
                    const pulseIcon = thinkingSummary.querySelector('.animate-pulse');
                    if (pulseIcon) {
                        pulseIcon.classList.remove('bg-blue-500', 'bg-yellow-500');
                        pulseIcon.classList.add('bg-green-500');
                    }
                }
            }
        } else {
            // 普通Skill：在final区域流式渲染内容
            if (finalEl) {
                finalEl.classList.remove('hidden');
                
                // 根据content_type实时渲染
                try {
                    const partialData = JSON.parse(data.accumulated);
                    
                    // 根据content_type渲染不同的UI
                    if (partialData.questions && Array.isArray(partialData.questions)) {
                        // Quiz Skill
                        finalEl.innerHTML = renderQuizStreamingUI(partialData);
                    } else if (partialData.cards && Array.isArray(partialData.cards)) {
                        // Flashcard Skill
                        finalEl.innerHTML = renderFlashcardStreamingUI(partialData);
                    } else if (partialData.concept) {
                        // Explanation Skill
                        finalEl.innerHTML = renderExplanationStreamingUI(partialData);
                    } else if (partialData.structured_notes) {
                        // Notes Skill
                        finalEl.innerHTML = renderNotesStreamingUI(partialData);
                    }
                } catch (e) {
                    // 🔥 JSON不完整，使用正则智能提取部分内容（支持未闭合字符串）
                    const acc = data.accumulated || '';
                    
                    // 辅助提取函数：提取key对应的值，支持未闭合的引号
                    const extract = (key) => {
                        // 匹配 "key": "value... (可能未闭合)
                        // [^"\\]* 匹配非引号和非转义字符
                        // (?:\\.[^"\\]*)* 匹配转义字符后的内容
                        const regex = new RegExp(`"${key}"\\s*:\\s*"((?:[^"\\\\]|\\\\.)*)`);
                        const match = acc.match(regex);
                        return match ? match[1] : null;
                    };

                    const partialData = {
                        concept: extract('concept'),
                        intuition: extract('intuition'),
                        formal_definition: extract('formal_definition'),
                        // 尝试提取数组项 (简化版)
                        questions: [],
                        cards: [],
                        examples: [],  // 🆕 添加 examples 数组
                        // Notes 提取
                        structured_notes: {
                            title: extract('title'),
                            sections: []
                        }
                    };
                    
                    // 提取所有 quiz questions
                    const questionMatches = acc.matchAll(/"question_text"\s*:\s*"((?:[^"\\\\]|\\\\.)*)/g);
                    for (const m of questionMatches) {
                        partialData.questions.push({ question_text: m[1] });
                    }
                    
                    // 提取所有 flashcards
                    const cardMatches = acc.matchAll(/"front"\s*:\s*"((?:[^"\\\\]|\\\\.)*)/g);
                    for (const m of cardMatches) {
                        partialData.cards.push({ front: m[1] });
                    }

                    // 🆕 提取 examples（example 和 explanation 字段）
                    const examplePattern = /"example"\s*:\s*"((?:[^"\\\\]|\\.)*)"/g;
                    const explanationPattern = /"explanation"\s*:\s*"((?:[^"\\\\]|\\.)*)"/g;
                    const exampleMatches = [...acc.matchAll(examplePattern)];
                    const explanationMatches = [...acc.matchAll(explanationPattern)];
                    
                    // 组合 example 和对应的 explanation
                    for (let i = 0; i < Math.max(exampleMatches.length, explanationMatches.length); i++) {
                        partialData.examples.push({
                            example: exampleMatches[i] ? exampleMatches[i][1] : '生成中...',
                            explanation: explanationMatches[i] ? explanationMatches[i][1] : ''
                        });
                    }

                    // 提取 notes sections
                    const sectionMatches = acc.matchAll(/"heading"\s*:\s*"((?:[^"\\\\]|\\\\.)*)/g);
                    for (const m of sectionMatches) {
                        partialData.structured_notes.sections.push({ heading: m[1], points: [] });
                    }
                    
                    // 提取 points (这里简化处理，因为points是嵌套的，正则提取比较困难，只能提取最近的)
                    // 实际上对于notes，只要有title和section heading，流式体验就已经很好了

                    // 如果提取到了任何内容，就尝试渲染
                    if (partialData.questions.length > 0) {
                        finalEl.innerHTML = renderQuizStreamingUI(partialData);
                    } else if (partialData.cards.length > 0) {
                        finalEl.innerHTML = renderFlashcardStreamingUI(partialData);
                    } else if (partialData.concept || partialData.intuition) {
                        finalEl.innerHTML = renderExplanationStreamingUI(partialData);
                    } else if (partialData.structured_notes.title || partialData.structured_notes.sections.length > 0) {
                        finalEl.innerHTML = renderNotesStreamingUI(partialData);
                    } else {
                        // 真的什么都没提取到，显示loading
                    if (!finalEl.innerHTML) {
                            finalEl.innerHTML = '<div class="text-center py-4"><div class="animate-pulse text-blue-500">📝 正在生成内容... (' + acc.length + ' 字符)</div></div>';
                        }
                    }
                }
            }
            
            // 更新thinking overview为"准备生成内容"
            const thinkingOverview = document.getElementById(`${responseId}-thinking-overview`);
            if (thinkingOverview) {
                const overviewText = document.getElementById(`${responseId}-thinking-overview-text`);
                if (overviewText && !overviewText.textContent.includes('准备生成')) {
                    overviewText.innerHTML = '⏳ <span class="animate-pulse">准备生成内容...</span>';
                    const pulseIcon = thinkingOverview.querySelector('.w-2.h-2');
                    if (pulseIcon) {
                        pulseIcon.classList.remove('bg-blue-500');
                        pulseIcon.classList.add('bg-yellow-500');
                    }
                }
            }
        }
        
        scrollToBottom();
    } 
    else if (data.type === 'done') {
        // 生成完成，渲染最终结果
        if (statusEl) statusEl.remove();
        
        // 🔍 Debug日志已注释以减少console噪音
        // console.log('[DEBUG] Done event data:', JSON.stringify(data, null, 2));
        // console.log('[DEBUG] data.content:', data.content);
        // console.log('[DEBUG] data.content.reasoning_summary:', data.content?.reasoning_summary);
        
        // 🆕 Done后隐藏thinking overview（用户只想在thinking过程中看到）
        const thinkingOverview = document.getElementById(`${responseId}-thinking-overview`);
        if (thinkingOverview) {
            // 隐藏overview，保留完整thinking section供用户展开查看
            thinkingOverview.classList.add('hidden');
            
            // 🐛 保存Debug数据到后端（如果有reasoning_summary）
            if (data.content && data.content.reasoning_summary && data.thinking) {
                saveThinkingOverviewDebug(responseId, data.thinking, data.content.reasoning_summary);
            }
        }
        
        if (!data.content || !data.content.reasoning_summary) {
            // ⚠️ Fallback：如果没有reasoning_summary，记录日志（已注释）
            // console.warn('[WARN] No reasoning_summary in done event');
            // console.log('[DEBUG] Available keys in data.content:', data.content ? Object.keys(data.content) : 'null');
        }
        
        // 检测是否是Plan Skill
        const planFinalResult = document.querySelector('#plan-final-result');
        const planFinalContent = document.querySelector('#plan-final-content');
        const isPlanSkill = planFinalResult && !planFinalResult.classList.contains('hidden');
        
        if (isPlanSkill && planFinalContent && data.content) {
            // Plan Skill：渲染到Plan内部
            planFinalResult.classList.remove('hidden');
            const contentType = data.content_type;
            
            // 渲染不同类型的卡片
            if (contentType === 'quiz_set' && data.content.questions) {
                planFinalContent.innerHTML = renderQuizCard(data.content);
            } else if (contentType === 'explanation' && data.content.concept) {
                planFinalContent.innerHTML = renderExplainCard(data.content);
            } else if (contentType === 'flashcard_set' && data.content.cards) {
                planFinalContent.innerHTML = renderFlashcardSet(data.content);
            } else if (contentType === 'learning_bundle' && data.content.components) {
                planFinalContent.innerHTML = renderLearningBundle(data.content);
            } else if (contentType === 'mindmap' && data.content.root) {
                planFinalContent.innerHTML = renderMindMapCard(data.content);
            } else if (contentType === 'notes' && data.content.structured_notes) {
                planFinalContent.innerHTML = renderNotesCard(data.content);
            } else {
                // 未知类型，显示JSON
                planFinalContent.innerHTML = `<div class="p-6"><pre class="text-sm">${JSON.stringify(data.content, null, 2)}</pre></div>`;
            }
        } else if (finalEl && data.content) {
            // 普通Skill：渲染到finalEl
            finalEl.classList.remove('hidden');
            const contentType = data.content_type;
            
            // 渲染不同类型的卡片
            if (contentType === 'quiz_set' && data.content.questions) {
                finalEl.innerHTML = renderQuizCard(data.content);
            } else if (contentType === 'explanation' && data.content.concept) {
                finalEl.innerHTML = renderExplainCard(data.content);
            } else if (contentType === 'flashcard_set' && data.content.cards) {
                finalEl.innerHTML = renderFlashcardSet(data.content);
            } else if (contentType === 'learning_bundle' && data.content.components) {
                finalEl.innerHTML = renderLearningBundle(data.content);
            } else if (contentType === 'mindmap' && data.content.root) {
                finalEl.innerHTML = renderMindMapCard(data.content);
            } else if (contentType === 'notes' && data.content.structured_notes) {
                finalEl.innerHTML = renderNotesCard(data.content);
            } else {
                // 未知类型，显示JSON
                finalEl.innerHTML = `<div class="p-6"><pre class="text-sm">${JSON.stringify(data.content, null, 2)}</pre></div>`;
            }
        }
        
        scrollToBottom();
        // console.log('✅ Stream finished');
    } 
    else if (data.type === 'error') {
        updateStreamError(responseId, data.message);
    }
}

function updateStreamError(responseId, message) {
    const container = document.getElementById(responseId);
    if (container) {
        container.innerHTML = `
            <div class="bg-center bg-no-repeat aspect-square bg-cover rounded-full size-10 shrink-0" style='background-image: url("https://lh3.googleusercontent.com/aida-public/AB6AXuCxe92kEf7gMHjbEHfZQu3F-p4XUO0nyA37zYAuOz7CiVXM_3hgmQ9gTI6zw7siePySKKolumdfXax7FjZ1tuLAnsb5rDYnZjw4LaKpR0MpYWUilv2DSX2VlCD416jAvXmMW3d3TA0MfMgLOkvyyvAqiNcFnqdLIk1LOdKh1Axylm3hUbhf-JtzopMhBhZ5WxEDvTgpGF0E65VLCr805vqY4iosbw4L8Qmm-sViAPSF8dXyszl2XldUnwHCnAakeX7o04PO1S6iwT_m");'></div>
            <div class="flex flex-1 flex-col gap-1 items-start">
                <p class="text-text-light-secondary dark:text-text-dark-secondary text-sm font-medium">StudyX Agent</p>
                <div class="w-full max-w-2xl rounded-xl border border-red-300 dark:border-red-700 bg-red-50 dark:bg-red-900/20 p-4">
                    <div class="flex items-start gap-3">
                        <svg class="w-6 h-6 text-red-600 dark:text-red-400 flex-shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"></path>
                        </svg>
                        <div class="flex-1">
                            <h3 class="text-base font-semibold text-red-800 dark:text-red-200 mb-2">发生错误</h3>
                            <p class="text-sm text-red-700 dark:text-red-300">${escapeHtml(message)}</p>
                        </div>
                    </div>
                </div>
            </div>
        `;
    }
}

// 添加加载消息
function addLoadingMessage() {
    const messagesDiv = document.getElementById('chatMessages').querySelector('.flex.flex-col.gap-6');
    const loadingMsg = `
        <div class="flex items-end gap-3 max-w-2xl" id="loadingMessage">
            <div class="bg-center bg-no-repeat aspect-square bg-cover rounded-full size-10 shrink-0" style='background-image: url("https://lh3.googleusercontent.com/aida-public/AB6AXuD4akB4LF1N3Soza8KZVpuDmX2j9J1Bm-Q7ClnC4wgqdXiZ6gWh0GikuESsR5ipv-M9eN48aHZTdCPsjIQAUFgiyvioA_Sk_14dwwbvFKoIJSRPlAq_kFDf1rz5-dqEkf9nEE2-5vA6R0ip58qcct5NzBXsF3iyDqi2LSJgsfUyXFItvX1CwxGl-MVLpHEufw0lwuexPO6Xkfn83jSdg42dyxyrjn8WNSJFcbSuhlcuscBOyRnZuEg6m5G2gYpvxIUvPJ_Cw1xWPRw8");'></div>
            <div class="flex flex-1 flex-col gap-1 items-start">
                <p class="text-text-light-secondary dark:text-text-dark-secondary text-sm font-medium">StudyX Agent</p>
                <div class="text-base font-normal leading-normal flex items-center gap-2 rounded-xl rounded-bl-none px-4 py-3 bg-surface-light dark:bg-surface-dark border border-border-light dark:border-border-dark text-text-light-primary dark:text-text-dark-primary">
                    <div class="w-1.5 h-1.5 rounded-full bg-text-light-secondary dark:bg-text-dark-secondary animate-[bounce_1s_infinite_0.1s]"></div>
                    <div class="w-1.5 h-1.5 rounded-full bg-text-light-secondary dark:bg-text-dark-secondary animate-[bounce_1s_infinite_0.2s]"></div>
                    <div class="w-1.5 h-1.5 rounded-full bg-text-light-secondary dark:bg-text-dark-secondary animate-[bounce_1s_infinite_0.3s]"></div>
                </div>
            </div>
        </div>
    `;
    messagesDiv.insertAdjacentHTML('beforeend', loadingMsg);
    scrollToBottom();
}

// 移除加载消息
function removeLoadingMessage() {
    const loadingMsg = document.getElementById('loadingMessage');
    if (loadingMsg) loadingMsg.remove();
}

// 渲染 QuizCard
// 🆕 渲染Plan预览卡片（每个步骤带独立的thinking区域）
function renderPlanPreview(topic, stepsPreview, totalSteps) {
    const stepsHtml = stepsPreview.map((step, idx) => {
        const stepNumber = step.step_order;
        const isFirst = idx === 0;
        const isLast = idx === stepsPreview.length - 1;
        
        return `
            <div id="plan-step-${stepNumber}" 
                 class="plan-step-item rounded-lg border-2 border-border-light dark:border-border-dark transition-all duration-300 overflow-hidden">
                <!-- 步骤头部 -->
                <div class="flex items-start gap-4 p-4">
                    <!-- 步骤编号和状态 -->
                    <div class="flex flex-col items-center gap-2">
                        <div class="w-12 h-12 rounded-full bg-primary/10 flex items-center justify-center flex-shrink-0 relative">
                            <span class="text-lg font-bold text-primary">${stepNumber}</span>
                            <!-- 🆕 进度环 -->
                            <svg class="absolute inset-0 w-12 h-12 -rotate-90" style="display:none;" id="plan-step-${stepNumber}-progress-ring">
                                <circle cx="24" cy="24" r="22" fill="none" stroke="currentColor" 
                                        class="text-gray-200 dark:text-gray-700" stroke-width="2"/>
                                <circle cx="24" cy="24" r="22" fill="none" stroke="currentColor" 
                                        class="text-primary transition-all duration-500" stroke-width="2"
                                        stroke-dasharray="138" stroke-dashoffset="138"
                                        id="plan-step-${stepNumber}-progress-circle"/>
                            </svg>
                        </div>
                        <div class="step-status-icon text-2xl">⏸️</div>
                        <!-- 🆕 时间追踪 -->
                        <div class="step-time-tracker text-xs text-text-light-secondary dark:text-text-dark-secondary hidden">
                            <span class="step-elapsed-time">0:00</span>
                        </div>
                    </div>
                    
                    <!-- 步骤内容 -->
                    <div class="flex-1 min-w-0">
                        <div class="flex items-center justify-between mb-2">
                            <h4 class="text-lg font-semibold text-text-light-primary dark:text-text-dark-primary">
                                ${escapeHtml(step.step_name)}
                            </h4>
                            <!-- 🆕 步骤状态标签 -->
                            <span class="step-status-label px-2 py-1 rounded-full text-xs font-medium bg-gray-100 dark:bg-gray-800 text-text-light-secondary dark:text-text-dark-secondary">
                                待执行
                            </span>
                        </div>
                        ${step.step_description ? `
                            <p class="text-sm text-text-light-secondary dark:text-text-dark-secondary mb-2">
                                ${escapeHtml(step.step_description)}
                            </p>
                        ` : ''}
                        <div class="flex items-center gap-2 text-xs text-text-light-secondary dark:text-text-dark-secondary">
                            <span class="px-2 py-1 rounded-full bg-gray-100 dark:bg-gray-800">
                                ${escapeHtml(step.skill_id)}
                            </span>
                        </div>
                        <!-- 🆕 Thinking Summary（简洁概括，支持多行） -->
                        <div id="plan-step-${stepNumber}-thinking-summary" class="hidden mt-3 flex items-start gap-2 text-xs text-blue-700 dark:text-blue-400">
                            <div class="w-2 h-2 rounded-full bg-blue-500 animate-pulse flex-shrink-0 mt-1"></div>
                            <span class="thinking-summary-text italic leading-relaxed">正在思考...</span>
                        </div>
                    </div>
                </div>
                
                <!-- 🆕 该步骤的完整Thinking内容（可折叠，默认展开） -->
                <div id="plan-step-${stepNumber}-thinking-full" class="hidden border-t border-border-light dark:border-border-dark bg-gray-50 dark:bg-gray-900/30">
                    <details class="group" open>
                        <summary class="flex items-center justify-between px-4 py-2 cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors">
                            <div class="flex items-center gap-2">
                                <svg class="w-4 h-4 text-primary transition-transform group-open:rotate-90" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"></path>
                                </svg>
                                <span class="text-xs font-semibold text-text-light-primary dark:text-text-dark-primary">💭 完整思考过程</span>
                            </div>
                        </summary>
                        <div class="px-4 py-3 border-t border-border-light dark:border-border-dark max-h-96 overflow-y-auto">
                            <pre id="plan-step-${stepNumber}-thinking-content" class="whitespace-pre-wrap text-xs text-text-light-secondary dark:text-text-dark-secondary leading-relaxed"></pre>
                        </div>
                    </details>
                </div>
                
                <!-- 🆕 该步骤的输出结果（步骤完成后立即显示） -->
                <div id="plan-step-${stepNumber}-output" class="hidden border-t border-border-light dark:border-border-dark bg-green-50 dark:bg-green-900/10 p-4">
                    <div class="flex items-center gap-2 mb-3">
                        <svg class="w-4 h-4 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"></path>
                        </svg>
                        <span class="text-xs font-semibold text-green-700 dark:text-green-400">✅ 步骤输出</span>
                    </div>
                    <div id="plan-step-${stepNumber}-output-content" class="w-full">
                        <!-- 该步骤的结果将渲染在这里 -->
                    </div>
                </div>
            </div>
        `;
    }).join('');
    
    return `
        <div class="w-full max-w-3xl">
            <div class="border-2 border-primary/30 rounded-xl overflow-hidden bg-gradient-to-br from-blue-50/50 to-purple-50/50 dark:from-blue-900/10 dark:to-purple-900/10">
                <!-- Header -->
                <div class="px-6 py-4 bg-primary/5 border-b border-primary/20">
                    <div class="flex items-center justify-between">
                        <div class="flex items-center gap-3">
                            <div class="w-10 h-10 rounded-full bg-primary flex items-center justify-center">
                                <span class="text-white text-xl">📚</span>
                            </div>
                            <div class="flex-1">
                                <h3 class="text-xl font-bold text-text-light-primary dark:text-text-dark-primary">
                                    学习包生成计划
                                </h3>
                                <p class="text-sm text-text-light-secondary dark:text-text-dark-secondary mt-1">
                                    主题：${escapeHtml(topic)} · 共 ${totalSteps} 个步骤
                                </p>
                            </div>
                        </div>
                        <!-- 🆕 Task Progress指示器 -->
                        <div id="plan-progress-indicator" class="px-4 py-2 rounded-lg bg-white dark:bg-gray-800 border border-primary/30">
                            <p class="text-xs text-text-light-secondary dark:text-text-dark-secondary mb-1">Task Progress</p>
                            <p class="text-2xl font-bold text-primary">
                                <span id="plan-progress-current">0</span>/<span id="plan-progress-total">${totalSteps}</span>
                            </p>
                        </div>
                    </div>
                </div>
                
                <!-- Steps -->
                <div class="p-6 space-y-4">
                    ${stepsHtml}
                </div>
                
                <!-- 🆕 Planning阶段提示 -->
                <div id="plan-planning-phase" class="px-6 py-4 bg-gradient-to-r from-blue-50 to-purple-50 dark:from-blue-900/20 dark:to-purple-900/20 border-t border-primary/20">
                    <div class="flex items-center gap-3">
                        <div class="w-6 h-6 rounded-full bg-primary/20 flex items-center justify-center animate-pulse">
                            <div class="w-3 h-3 rounded-full bg-primary"></div>
                        </div>
                        <div class="flex-1">
                            <p class="text-sm font-semibold text-primary">
                                🎯 Prioritizing Curated Steps
                            </p>
                            <p class="text-xs text-text-light-secondary dark:text-text-dark-secondary mt-1">
                                正在为您规划最佳学习路径...
                            </p>
                        </div>
                    </div>
                </div>
                
                <!-- 🆕 最终结果区域（在Plan内部） -->
                <div id="plan-final-result" class="hidden border-t-2 border-primary/30">
                    <div class="px-6 py-4 bg-green-50 dark:bg-green-900/20">
                        <h4 class="text-lg font-bold text-green-700 dark:text-green-400 flex items-center gap-2">
                            <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"></path>
                            </svg>
                            ✅ 学习包生成完成
                        </h4>
                    </div>
                    <div id="plan-final-content" class="p-6 bg-white dark:bg-gray-800"></div>
                </div>
            </div>
        </div>
    `;
}

// 🆕 渲染思考过程（支持Markdown和LaTeX）
function renderThinkingProcess(thinking) {
    if (!thinking) return '';
    
    // 简单的Markdown渲染：**粗体**
    let renderedText = escapeHtml(thinking)
        .replace(/\*\*(.*?)\*\*/g, '<strong class="font-semibold">$1</strong>');
    
    return `
        <div class="w-full max-w-3xl mb-4">
            <details class="group border border-border-light dark:border-border-dark rounded-lg overflow-hidden bg-surface-light dark:bg-surface-dark">
                <summary class="flex items-center justify-between px-4 py-3 cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors">
                    <div class="flex items-center gap-2">
                        <svg class="w-5 h-5 text-primary transition-transform group-open:rotate-90" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"></path>
                        </svg>
                        <span class="text-base font-semibold text-text-light-primary dark:text-text-dark-primary">🧠 思考过程</span>
                    </div>
                    <span class="text-xs text-text-light-secondary dark:text-text-dark-secondary">点击展开</span>
                </summary>
                <div class="px-4 py-3 border-t border-border-light dark:border-border-dark bg-gray-50 dark:bg-gray-900">
                    <div class="prose prose-sm dark:prose-invert max-w-none">
                        <pre class="whitespace-pre-wrap text-sm text-text-light-secondary dark:text-text-dark-secondary leading-relaxed thinking-content">${renderedText}</pre>
                    </div>
                </div>
            </details>
        </div>
    `;
}

function renderQuizCard(content) {
    const questions = content.questions || [];
    if (questions.length === 0) return '<p>暂无题目</p>';
    
    // 🆕 添加思考过程
    let html = renderThinkingProcess(content._thinking);
    
    html += '<div class="flex flex-col gap-6 w-full">';
    
    questions.forEach((q, idx) => {
        html += `
            <div class="flex flex-col gap-6 rounded-xl border border-border-light dark:border-border-dark bg-surface-light dark:bg-surface-dark p-6 shadow-sm">
                <div class="flex flex-col gap-3">
                    <p class="text-primary text-base font-medium">${content.subject || '练习题'}</p>
                    <div class="rounded bg-slate-200 dark:bg-slate-700">
                        <div class="h-2 rounded bg-primary" style="width: ${((idx + 1) / questions.length * 100)}%;"></div>
                    </div>
                    <p class="text-slate-500 dark:text-slate-400 text-sm">Question ${idx + 1} of ${questions.length}</p>
                </div>
                <div class="border-t border-border-light dark:border-border-dark"></div>
                <h1 class="text-text-light-primary dark:text-text-dark-primary tracking-tight text-xl font-bold">${q.question_text || ''}</h1>
                <div class="flex flex-col gap-3" style="--radio-dot-svg: url('data:image/svg+xml,%3csvg viewBox=%270 0 16 16%27 fill=%27rgb(19,127,236)%27 xmlns=%27http://www.w3.org/2000/svg%27%3e%3ccircle cx=%278%27 cy=%278%27 r=%273%27/%3e%3c/svg%3e');">`;
        
        (q.options || []).forEach((opt) => {
            html += `
                    <label class="flex items-center gap-4 rounded-lg border border-solid border-border-light dark:border-border-dark p-4 cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-800/50 has-[:checked]:border-primary has-[:checked]:bg-primary/10">
                        <input class="h-5 w-5 border-2 border-border-light dark:border-border-dark bg-transparent text-transparent checked:border-primary checked:bg-[image:--radio-dot-svg] focus:outline-none focus:ring-0" name="quiz_${idx}" type="radio"/>
                        <div class="flex grow flex-col"><p class="text-text-light-primary dark:text-text-dark-primary text-sm font-medium">${opt}</p></div>
                    </label>`;
        });
        
        html += `
                </div>`;
        
        if (q.explanation) {
            html += `
                <div class="flex flex-col gap-4 rounded-lg bg-slate-50 dark:bg-slate-800/50 p-4 mt-2">
                    <h3 class="text-lg font-bold text-text-light-primary dark:text-text-dark-primary">解析</h3>
                    <p class="text-sm text-slate-600 dark:text-slate-300">${q.explanation}</p>
                    <p class="text-sm text-primary font-medium">正确答案: ${q.correct_answer}</p>
                </div>`;
        }
        
        html += `
            </div>`;
    });
    
    html += '</div>';
    return html;
}

// 渲染 ExplainCard
function renderExplainCard(content) {
    const concept = content.concept || '';
    const intuition = content.intuition || '';
    const formalDef = content.formal_definition || '';
    const examples = content.examples || [];
    
    // 🆕 添加思考过程
    let html = renderThinkingProcess(content._thinking);
    html += `
        <div class="w-full rounded-xl border border-border-light dark:border-border-dark bg-surface-light dark:bg-surface-dark shadow-sm">
            <div class="p-6">
                <h1 class="text-2xl font-bold text-text-light-primary dark:text-text-dark-primary tracking-tight">${concept}</h1>
            </div>
            <div class="px-6 pb-6 text-base text-text-light-primary dark:text-text-dark-primary space-y-4">
                <p>${intuition}</p>`;
    
    if (formalDef) {
        html += `
                <div class="my-4 p-4 bg-background-light dark:bg-background-dark rounded-lg font-mono text-sm">
                    <span class="font-bold">${formalDef}</span>
                </div>`;
    }
    
    if (examples && examples.length > 0) {
        html += `
            </div>
            <hr class="border-border-light dark:border-border-dark"/>
            <div class="p-6">
                <h2 class="text-xl font-semibold text-text-light-primary dark:text-text-dark-primary mb-5">例子</h2>
                <div class="space-y-6">`;
        
        examples.forEach((ex, idx) => {
            html += `
                    <div class="flex flex-col gap-3">
                        <h3 class="font-semibold text-text-light-primary dark:text-text-dark-primary">
                            <span class="bg-primary text-white rounded-full h-6 w-6 inline-flex items-center justify-center text-sm mr-2">${idx + 1}</span>
                            ${ex.example || ex.title || ex.problem || '例子 ' + (idx + 1)}
                        </h3>
                        <div class="pl-8 text-slate-600 dark:text-slate-300 border-l-2 border-primary/50 ml-3">
                            <p>${ex.explanation || ex.solution || ''}</p>
                        </div>
                    </div>`;
        });
        
        html += `
                </div>`;
    }
    
    html += `
            </div>
        </div>`;
    
    return html;
}

// 渲染 FlashcardSet
function renderFlashcardSet(content) {
    const cards = content.cards || [];
    if (cards.length === 0) return '<p>暂无抽认卡</p>';
    
    // 🆕 添加思考过程
    let html = renderThinkingProcess(content._thinking);
    html += '<div class="flex flex-col gap-4 w-full">';
    html += `<h3 class="text-lg font-bold text-text-light-primary dark:text-text-dark-primary">📚 抽认卡集合</h3>`;
    
    cards.forEach((card, idx) => {
        html += `
            <div class="rounded-xl border border-border-light dark:border-border-dark bg-surface-light dark:bg-surface-dark p-6 shadow-sm">
                <div class="flex items-center gap-2 mb-4">
                    <span class="bg-primary text-white rounded-full h-6 w-6 inline-flex items-center justify-center text-sm">${idx + 1}</span>
                    <span class="text-sm text-slate-500">${card.card_type || 'basic'}</span>
                </div>
                <div class="space-y-4">
                    <div>
                        <p class="text-sm font-medium text-slate-500 mb-2">正面（Front）</p>
                        <p class="text-base text-text-light-primary dark:text-text-dark-primary">${card.front}</p>
                    </div>
                    <div class="border-t border-border-light dark:border-border-dark pt-4">
                        <p class="text-sm font-medium text-slate-500 mb-2">背面（Back）</p>
                        <p class="text-base text-text-light-primary dark:text-text-dark-primary">${card.back}</p>
                    </div>`;
        
        if (card.hints && card.hints.length > 0) {
            html += `
                    <div class="bg-slate-50 dark:bg-slate-800/50 p-3 rounded-lg">
                        <p class="text-sm font-medium text-primary mb-1">💡 提示</p>
                        <ul class="text-sm text-slate-600 dark:text-slate-300 list-disc list-inside">
                            ${card.hints.map(h => `<li>${h}</li>`).join('')}
                        </ul>
                    </div>`;
        }
        
        html += `
                </div>
            </div>`;
    });
    
    html += '</div>';
    return html;
}

// 渲染 Notes (学习笔记) - Notebook 风格，支持编辑
function renderNotesCard(content) {
    const notes = content.structured_notes || {};
    const sections = notes.sections || [];
    const notesId = content.notes_id || `notes_${Date.now()}`;
    
    let html = `
        <div class="w-full rounded-xl border-2 border-border-light dark:border-border-dark bg-white dark:bg-gray-800 shadow-lg overflow-hidden notebook-container" id="notes_${notesId}" data-notes-id="${notesId}">
            <!-- 笔记头部 -->
            <div class="bg-gradient-to-r from-blue-500 to-purple-600 p-6">
                <div class="flex items-center justify-between">
                    <div class="flex items-center gap-3">
                        <span class="material-symbols-outlined text-white text-3xl">description</span>
                        <div>
                            <p class="text-sm text-blue-100">${content.subject || '学习笔记'}</p>
                            <h3 class="text-2xl font-bold text-white editable-title" contenteditable="false">${notes.title || content.topic || '笔记'}</h3>
                        </div>
                    </div>
                    <div class="flex gap-2">
                        <button onclick="toggleEditMode('${notesId}')" class="edit-btn px-4 py-2 bg-white/20 hover:bg-white/30 text-white rounded-lg transition-all flex items-center gap-2">
                            <span class="material-symbols-outlined text-sm">edit</span>
                            <span class="edit-text">编辑</span>
                        </button>
                        <button onclick="saveNotes('${notesId}')" class="save-btn hidden px-4 py-2 bg-green-500 hover:bg-green-600 text-white rounded-lg transition-all flex items-center gap-2">
                            <span class="material-symbols-outlined text-sm">save</span>
                            <span>保存</span>
                        </button>
                        <button onclick="cancelEdit('${notesId}')" class="cancel-btn hidden px-4 py-2 bg-red-500 hover:bg-red-600 text-white rounded-lg transition-all flex items-center gap-2">
                            <span class="material-symbols-outlined text-sm">close</span>
                            <span>取消</span>
                        </button>
                    </div>
                </div>
            </div>
            
            <!-- 笔记内容区域 -->
            <div class="p-8 space-y-6 notes-content bg-amber-50/30 dark:bg-gray-900/30">`;
    
    sections.forEach((section, idx) => {
        html += `
            <div class="notebook-section bg-white dark:bg-gray-800 rounded-lg p-6 border-l-4 border-blue-500 shadow-sm hover:shadow-md transition-shadow" data-section-id="${idx}">
                <div class="flex items-center justify-between mb-4">
                    <h4 class="text-xl font-bold text-gray-800 dark:text-gray-100 section-heading" contenteditable="false">
                        ${section.heading}
                    </h4>
                    <button onclick="addBulletPoint('${notesId}', ${idx})" class="add-point-btn hidden text-blue-500 hover:text-blue-700 p-1">
                        <span class="material-symbols-outlined text-sm">add_circle</span>
                    </button>
                </div>
                <ul class="space-y-3 bullet-list">`;
        
        (section.bullet_points || []).forEach((point, pointIdx) => {
            html += `
                <li class="flex items-start gap-3 group" data-point-id="${pointIdx}">
                    <span class="text-blue-500 mt-1 text-lg">•</span>
                    <span class="flex-1 text-base text-gray-700 dark:text-gray-300 leading-relaxed bullet-point" contenteditable="false">${point}</span>
                    <button onclick="removeBulletPoint('${notesId}', ${idx}, ${pointIdx})" class="delete-point-btn hidden opacity-0 group-hover:opacity-100 text-red-400 hover:text-red-600 transition-opacity p-1">
                        <span class="material-symbols-outlined text-sm">delete</span>
                    </button>
                </li>`;
        });
        
        html += `
                </ul>
            </div>`;
    });
    
    html += `
            </div>
            
            <!-- 笔记底部 -->
            <div class="bg-gray-50 dark:bg-gray-900 px-8 py-4 border-t border-gray-200 dark:border-gray-700">
                <p class="text-sm text-gray-500 dark:text-gray-400">
                    <span class="material-symbols-outlined text-xs align-middle">info</span>
                    点击"编辑"按钮进入编辑模式，可以修改标题、章节标题和要点内容
                </p>
            </div>
        </div>`;
    
    return html;
}

// 渲染 Learning Bundle
function renderLearningBundle(content) {
    const components = content.components || [];
    if (components.length === 0) return '<p>暂无学习资料</p>';
    
    let html = '<div class="flex flex-col gap-6 w-full">';
    html += `
        <div class="rounded-xl border border-primary/50 bg-primary/5 p-4">
            <h3 class="text-xl font-bold text-primary mb-2">📦 完整学习包</h3>
            <p class="text-sm text-slate-600 dark:text-slate-300">${content.learning_path ? content.learning_path.join(' → ') : '包含多个学习组件'}</p>
            ${content.estimated_time_minutes ? `<p class="text-sm text-primary mt-2">⏱️ 预计学习时间：${content.estimated_time_minutes} 分钟</p>` : ''}
        </div>`;
    
    components.forEach((comp, idx) => {
        html += `<div class="border-l-4 border-primary pl-4">`;
        
        // 🆕 支持所有 5 种组件类型
        const typeNames = {
            'explanation': '概念讲解',
            'quiz': '练习题',
            'flashcard': '抽认卡',
            'notes': '学习笔记',
            'mindmap': '知识结构图'
        };
        const typeName = typeNames[comp.component_type] || comp.component_type;
        
        html += `<h4 class="text-md font-bold text-primary mb-3">第 ${idx + 1} 部分：${typeName}</h4>`;
        
        if (comp.component_type === 'explanation' && comp.content.concept) {
            html += renderExplainCard(comp.content);
        } else if (comp.component_type === 'quiz' && comp.content.questions) {
            html += renderQuizCard(comp.content);
        } else if (comp.component_type === 'flashcard' && comp.content.cards) {
            html += renderFlashcardSet(comp.content);
        } else if (comp.component_type === 'notes' && comp.content.structured_notes) {
            html += renderNotesCard(comp.content);
        } else if (comp.component_type === 'mindmap' && comp.content.root) {
            html += renderMindMapCard(comp.content);
        } else {
            html += `<pre class="text-xs">${JSON.stringify(comp.content, null, 2)}</pre>`;
        }
        
        html += `</div>`;
    });
    
    html += '</div>';
    return html;
}

// 渲染 MindMap (思维导图)
function renderMindMapCard(content) {
    if (!content.root) {
        return '<p>思维导图数据格式错误</p>';
    }
    
    // 生成唯一 ID
    const mindmapId = `mindmap-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
    
    let html = `
        <div class="w-full rounded-xl border border-border-light dark:border-border-dark bg-surface-light dark:bg-surface-dark shadow-sm overflow-hidden">
            <div class="p-4 border-b border-border-light dark:border-border-dark">
                <div class="flex items-center justify-between">
                    <div class="flex items-center gap-3">
                        <span class="material-symbols-outlined text-primary text-2xl">account_tree</span>
                        <div>
                            <h3 class="text-lg font-bold text-text-light-primary dark:text-text-dark-primary">${content.subject || '思维导图'} - ${content.topic || ''}</h3>
                            <p class="text-sm text-slate-500 dark:text-slate-400">${content.structure_summary || ''}</p>
                        </div>
                    </div>
                    <div class="flex items-center gap-2">
                        <span class="material-symbols-outlined text-sm text-slate-500">edit</span>
                        <span class="text-xs text-slate-500">可编辑</span>
                    </div>
                </div>
            </div>
            <div id="${mindmapId}" class="w-full" style="height: 600px; background: #fff;"></div>
            <div class="p-3 border-t border-border-light dark:border-border-dark bg-slate-50 dark:bg-slate-800">
                <p class="text-xs text-slate-600 dark:text-slate-400">
                    💡 提示：右键点击节点可以添加、编辑、删除节点。支持拖拽移动节点位置。按 Tab 添加子节点，Enter 添加兄弟节点。
                </p>
            </div>
        </div>
    `;
    
    // 延迟初始化 Mind Elixir（等待 DOM 插入）
    setTimeout(() => {
        initializeMindMap(mindmapId, content);
    }, 100);
    
    return html;
}

// 初始化思维导图（支持编辑功能）
function initializeMindMap(containerId, mindmapData) {
    const container = document.getElementById(containerId);
    if (!container) {
        console.error(`容器 ${containerId} 未找到`);
        return;
    }
    
    if (typeof MindElixir === 'undefined') {
        console.error('Mind Elixir 库未加载');
        container.innerHTML = '<p class="p-4 text-red-500">思维导图库加载失败，请刷新页面重试</p>';
        return;
    }
    
    try {
        // 转换数据格式为 Mind Elixir 格式
        const mindElixirData = convertToMindElixirFormat(mindmapData);
        
        // 初始化 Mind Elixir（启用编辑功能）
        const mind = new MindElixir({
            el: container,
            direction: MindElixir.SIDE,
            draggable: true,              // 启用拖拽
            contextMenu: true,            // 启用右键菜单
            toolBar: true,                // 启用工具栏（添加、删除节点等）
            keypress: true,               // 启用快捷键
            locale: 'zh_CN',
            allowUndo: true,              // 启用撤销/重做
            overflowHidden: false,
            primaryLinkStyle: 2,
            primaryNodeVerticalGap: 15,
            primaryNodeHorizontalGap: 65,
            contextMenuOption: {
                focus: true,
                link: true,
                extend: [
                    {
                        name: '添加子节点',
                        onclick: () => {
                            mind.addChild();
                        },
                    },
                    {
                        name: '添加兄弟节点',
                        onclick: () => {
                            mind.insertSibling();
                        },
                    },
                    {
                        name: '编辑节点',
                        onclick: () => {
                            mind.beginEdit();
                        },
                    },
                    {
                        name: '删除节点',
                        onclick: () => {
                            mind.removeNode();
                        },
                    },
                ],
            },
            before: {
                insertSibling(el, obj) {
                    console.log('插入兄弟节点');
                    return true;
                },
                async addChild(el, obj) {
                    console.log('添加子节点');
                    return true;
                },
            },
        });
        
        // 加载数据
        mind.init(mindElixirData);
        
        // 监听节点变化事件
        if (mind.bus && typeof mind.bus.addListener === 'function') {
            mind.bus.addListener('operation', (operation) => {
                console.log('思维导图操作:', operation.name);
                // 可以在这里保存到后端
            });
            
            mind.bus.addListener('nodeSelect', (node) => {
                console.log('选中节点:', node.nodeData.topic);
            });
        }
        
        console.log('✅ 思维导图渲染成功（支持编辑）:', containerId);
    } catch (error) {
        console.error('思维导图渲染失败:', error);
        container.innerHTML = `<p class="p-4 text-red-500">思维导图渲染失败: ${error.message}</p>`;
    }
}

// 渲染首次访问引导（Onboarding）
function renderOnboardingCard(content) {
    const { welcome, message, suggestions, call_to_action } = content;
    
    let html = `
        <div class="w-full max-w-3xl rounded-xl border border-border-light dark:border-border-dark bg-surface-light dark:bg-surface-dark shadow-lg overflow-hidden">
            <!-- Header -->
            <div class="p-6 bg-gradient-to-r from-indigo-500 via-purple-500 to-pink-500">
                <div class="flex items-center gap-3">
                    <span class="material-symbols-outlined text-white text-4xl">celebration</span>
                    <div>
                        <h3 class="text-2xl font-bold text-white">${welcome}</h3>
                        <p class="text-sm text-indigo-100 mt-1">${message}</p>
                    </div>
                </div>
            </div>
            
            <!-- Topic Suggestions -->
            <div class="p-6">
                <p class="text-base font-semibold text-slate-700 dark:text-slate-300 mb-4">
                    🎯 我可以帮您学习以下学科：
                </p>
                
                <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">`;
    
    suggestions.forEach(category => {
        html += `
                    <div class="border border-slate-300 dark:border-slate-600 rounded-lg p-4 hover:border-primary hover:shadow-md transition-all">
                        <div class="flex items-center gap-2 mb-3">
                            <span class="text-2xl">${category.icon}</span>
                            <h4 class="font-bold text-slate-800 dark:text-slate-200">${category.category}</h4>
                        </div>
                        <div class="flex flex-wrap gap-2">`;
        
        category.topics.forEach(topic => {
            html += `
                            <button 
                                onclick="startLearning('${topic.replace(/'/g, "\\'")}')"
                                class="px-3 py-1 text-sm rounded-full border border-slate-300 dark:border-slate-600 
                                       hover:bg-primary hover:text-white hover:border-primary transition-all
                                       text-slate-700 dark:text-slate-300">
                                ${topic}
                            </button>`;
        });
        
        html += `
                        </div>
                    </div>`;
    });
    
    html += `
                </div>
            </div>
            
            <!-- Call to Action -->
            <div class="p-4 bg-gradient-to-r from-blue-50 to-purple-50 dark:from-blue-900/20 dark:to-purple-900/20 border-t border-slate-200 dark:border-slate-700">
                <div class="flex items-start gap-3">
                    <span class="material-symbols-outlined text-primary text-2xl">lightbulb</span>
                    <p class="text-sm text-slate-700 dark:text-slate-300 flex-1">
                        ${call_to_action}
                    </p>
                </div>
            </div>
        </div>
    `;
    
    return html;
}

// 处理开始学习（从onboarding）
function startLearning(topic) {
    console.log('🎓 Start learning:', topic);
    
    // 构建消息并设置到输入框
    const message = `讲讲${topic}`;
    const input = document.getElementById('messageInput');
    input.value = message;
    
    // 调用 handleSend 会自动：
    // 1. 显示用户消息
    // 2. 发送到后端
    // 3. 显示 Agent 响应
    handleSend();
}

// 渲染澄清请求（Clarification）
function renderClarificationCard(content) {
    const { question, learned_topics, suggestion } = content;
    
    let html = `
        <div class="w-full max-w-2xl rounded-xl border border-border-light dark:border-border-dark bg-surface-light dark:bg-surface-dark shadow-sm overflow-hidden">
            <!-- Header -->
            <div class="p-4 bg-gradient-to-r from-blue-500 to-purple-500">
                <div class="flex items-center gap-3">
                    <span class="material-symbols-outlined text-white text-3xl">help_outline</span>
                    <div>
                        <h3 class="text-xl font-bold text-white">需要您的选择</h3>
                        <p class="text-sm text-blue-100">Please clarify your request</p>
                    </div>
                </div>
            </div>
            
            <!-- Question -->
            <div class="p-6 border-b border-border-light dark:border-border-dark">
                <p class="text-lg text-text-light-primary dark:text-text-dark-primary mb-4">
                    ${question}
                </p>
                
                <!-- Learned Topics -->
                <div class="space-y-2">
                    <p class="text-sm font-semibold text-slate-600 dark:text-slate-400 mb-3">📚 您最近学习过：</p>`;
    
    learned_topics.forEach((item, idx) => {
        const icon = item.type === 'explanation' ? '📖' : 
                     item.type === 'quiz_set' ? '✏️' : 
                     item.type === 'flashcard_set' ? '🎴' : '📝';
        html += `
                    <button 
                        onclick="selectTopic('${item.topic.replace(/'/g, "\\'")}', '${content.intent || 'notes'}')"
                        class="w-full text-left px-4 py-3 rounded-lg border border-slate-300 dark:border-slate-600 
                               hover:border-primary hover:bg-blue-50 dark:hover:bg-blue-900/20 transition-all
                               text-text-light-primary dark:text-text-dark-primary">
                        <span class="mr-2">${icon}</span>
                        <span class="font-medium">${item.topic}</span>
                    </button>`;
    });
    
    html += `
                </div>
            </div>
            
            <!-- Suggestion -->
            <div class="p-4 bg-slate-50 dark:bg-slate-800/50">
                <p class="text-sm text-slate-600 dark:text-slate-400">
                    💡 ${suggestion}
                </p>
            </div>
        </div>
    `;
    
    return html;
}

// 处理用户选择主题
function selectTopic(topic, intent) {
    console.log('🎯 User selected topic:', topic, 'for intent:', intent);
    
    // 根据intent构建消息（支持所有skills）
    const intentMessages = {
        'notes': `做${topic}的笔记`,
        'quiz_request': `生成${topic}的题目`,
        'flashcard_request': `生成${topic}的闪卡`,
        'explain_request': `讲解${topic}`,
        'mindmap': `生成${topic}的思维导图`,
        'learning_bundle': `获取${topic}的学习资料`
    };
    
    const message = intentMessages[intent] || `学习${topic}`;
    
    // 设置消息到输入框并发送
    const input = document.getElementById('messageInput');
    input.value = message;
    
    // 调用 handleSend 会自动：
    // 1. 显示用户消息到聊天界面
    // 2. 发送到后端
    // 3. 显示 Agent 响应
    handleSend();
}

// 将后端数据转换为 Mind Elixir 格式
function convertToMindElixirFormat(mindmapData) {
    console.log('🔄 Converting mindmap data:', mindmapData);
    
    if (!mindmapData || !mindmapData.root) {
        console.error('❌ Invalid mindmap data: missing root');
        throw new Error('思维导图数据格式错误：缺少根节点');
    }
    
    const children = mindmapData.root.children || [];
    console.log(`📊 Root has ${children.length} children`);
    
    return {
        nodeData: {
            id: mindmapData.root.id || 'root',
            topic: mindmapData.root.text || '未命名',
            children: children.map(convertMindMapNode),
            style: {
                fontSize: '18px',
                color: mindmapData.root.color || '#10b981',
                fillColor: '#fff',
                borderColor: mindmapData.root.color || '#10b981',
                borderWidth: 2,
            },
        },
    };
}

// 递归转换节点
function convertMindMapNode(node) {
    return {
        id: node.id,
        topic: node.text,
        children: node.children?.map(convertMindMapNode) || [],
        style: {
            fontSize: '14px',
            color: node.color || '#333',
            fillColor: '#fff',
            borderColor: node.color || '#ccc',
            borderWidth: 1,
        },
    };
}

// 添加 Agent 响应
function addAgentMessage(data) {
    const messagesDiv = document.getElementById('chatMessages').querySelector('.flex.flex-col.gap-6');
    
    // 🔍 调试：打印完整响应
    console.log('📥 Agent response:', {
        content_type: data.content_type,
        intent: data.intent,
        skill_id: data.skill_id,
        has_structured_notes: !!data.response_content?.structured_notes,
        response_content_keys: Object.keys(data.response_content || {}),
        full_response: data
    });
    
    // 根据 content_type 渲染不同的卡片
    let contentHtml = '';
    
    if (data.content_type === 'mixed_response' && data.response_content.results) {
        // 混合请求：渲染多个结果（DEBUG日志已注释）
        // console.log('🎭 Mixed response results:', data.response_content.results);
        // data.response_content.results.forEach((result, idx) => {
        //     console.log(`📦 Result ${idx + 1}:`, {
        //         content_type: result.content_type,
        //         has_structured_notes: !!result.content?.structured_notes,
        //         content_keys: Object.keys(result.content || {})
        //     });
        // });
        
        contentHtml = '<div class="flex flex-col gap-6 w-full">';
        data.response_content.results.forEach((result, idx) => {
            contentHtml += `<div class="border-l-4 border-primary pl-4">`;
            contentHtml += `<h3 class="text-lg font-bold text-primary mb-3">📦 结果 ${idx + 1}</h3>`;
            
            if (result.content_type === 'quiz_set' && result.content.questions) {
                contentHtml += renderQuizCard(result.content);
            } else if (result.content_type === 'explanation' && result.content.concept) {
                contentHtml += renderExplainCard(result.content);
            } else if (result.content_type === 'flashcard_set' && result.content.cards) {
                contentHtml += renderFlashcardSet(result.content);
            } else if (result.content_type === 'learning_bundle' && result.content.components) {
                contentHtml += renderLearningBundle(result.content);
            } else if (result.content_type === 'mindmap' && result.content.root) {
                contentHtml += renderMindMapCard(result.content);
            } else if (result.content_type === 'notes' && result.content.structured_notes) {
                contentHtml += renderNotesCard(result.content);
            } else {
                contentHtml += `<pre class="text-xs">${JSON.stringify(result.content, null, 2)}</pre>`;
            }
            
            contentHtml += `</div>`;
        });
        contentHtml += '</div>';
    } else if (data.content_type === 'quiz_set' && data.response_content.questions) {
        contentHtml = renderQuizCard(data.response_content);
    } else if (data.content_type === 'explanation' && data.response_content.concept) {
        // Debug 日志已注释
        // console.log('Explanation content:', data.response_content);
        // console.log('Examples:', data.response_content.examples);
        contentHtml = renderExplainCard(data.response_content);
    } else if (data.content_type === 'flashcard_set' && data.response_content.cards) {
        contentHtml = renderFlashcardSet(data.response_content);
    } else if (data.content_type === 'learning_bundle' && data.response_content.components) {
        contentHtml = renderLearningBundle(data.response_content);
    } else if (data.content_type === 'mindmap' && data.response_content.root) {
        // 思维导图渲染
        contentHtml = renderMindMapCard(data.response_content);
    } else if (data.content_type === 'notes') {
        // 学习笔记渲染（DEBUG日志已注释）
        // console.log('📝 渲染笔记, response_content:', data.response_content);
        if (data.response_content.structured_notes) {
            contentHtml = renderNotesCard(data.response_content);
        } else {
            console.warn('⚠️ Notes 数据结构不正确，缺少 structured_notes');
            contentHtml = `<pre class="text-xs overflow-auto p-4 bg-gray-100 dark:bg-gray-800 rounded">${JSON.stringify(data.response_content, null, 2)}</pre>`;
        }
    } else if (data.content_type === 'onboarding') {
        // 🆕 首次访问引导
        contentHtml = renderOnboardingCard(data.response_content);
    } else if (data.content_type === 'clarification') {
        // 🆕 澄清请求：询问用户选择主题
        // ✅ 传递完整的 data，包含 intent 信息
        contentHtml = renderClarificationCard({
            ...data.response_content,
            intent: data.intent  // ← 显式传递 intent
        });
    } else if (data.content_type === 'text' && data.response_content.text) {
        // 文本对话（如 "other" 意图）
        contentHtml = renderThinkingProcess(data.response_content._thinking);
        contentHtml += `<p class="text-base font-normal leading-normal rounded-xl rounded-bl-none px-4 py-3 bg-surface-light dark:bg-surface-dark border border-border-light dark:border-border-dark text-text-light-primary dark:text-text-dark-primary whitespace-pre-wrap max-w-2xl">${data.response_content.text}</p>`;
    } else if (data.content_type === 'error') {
        // 🆕 Error 类型专门处理（包含思考过程）
        contentHtml = renderThinkingProcess(data.response_content._thinking);
        contentHtml += `<div class="w-full max-w-2xl rounded-xl border border-red-300 dark:border-red-700 bg-red-50 dark:bg-red-900/20 p-4">
            <div class="flex items-start gap-3">
                <svg class="w-6 h-6 text-red-600 dark:text-red-400 flex-shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"></path>
                </svg>
                <div class="flex-1">
                    <h3 class="text-base font-semibold text-red-800 dark:text-red-200 mb-2">${data.response_content.error || '发生错误'}</h3>
                    ${data.response_content.suggestion ? `<p class="text-sm text-red-700 dark:text-red-300">${data.response_content.suggestion}</p>` : ''}
                </div>
            </div>
        </div>`;
    } else {
        // 默认渲染 JSON（也包含思考过程）
        contentHtml = renderThinkingProcess(data.response_content._thinking);
        contentHtml += `<p class="text-base font-normal leading-normal rounded-xl rounded-bl-none px-4 py-3 bg-surface-light dark:bg-surface-dark border border-border-light dark:border-border-dark text-text-light-primary dark:text-text-dark-primary whitespace-pre-wrap font-mono text-xs overflow-x-auto max-w-2xl">${JSON.stringify(data.response_content, null, 2)}</p>`;
    }
    
    const agentMsg = `
        <div class="flex items-start gap-3 w-full">
            <div class="bg-center bg-no-repeat aspect-square bg-cover rounded-full size-10 shrink-0" style='background-image: url("https://lh3.googleusercontent.com/aida-public/AB6AXuCxe92kEf7gMHjbEHfZQu3F-p4XUO0nyA37zYAuOz7CiVXM_3hgmQ9gTI6zw7siePySKKolumdfXax7FjZ1tuLAnsb5rDYnZjw4LaKpR0MpYWUilv2DSX2VlCD416jAvXmMW3d3TA0MfMgLOkvyyvAqiNcFnqdLIk1LOdKh1Axylm3hUbhf-JtzopMhBhZ5WxEDvTgpGF0E65VLCr805vqY4iosbw4L8Qmm-sViAPSF8dXyszl2XldUnwHCnAakeX7o04PO1S6iwT_m");'></div>
            <div class="flex flex-1 flex-col gap-1 items-start w-full">
                <p class="text-text-light-secondary dark:text-text-dark-secondary text-sm font-medium">StudyX Agent</p>
                ${contentHtml}
            </div>
        </div>
    `;
    messagesDiv.insertAdjacentHTML('beforeend', agentMsg);
    scrollToBottom();
}

// 添加错误消息
function addErrorMessage(errorText) {
    const messagesDiv = document.getElementById('chatMessages').querySelector('.flex.flex-col.gap-6');
    const errorMsg = `
        <div class="flex items-end gap-3 max-w-2xl">
            <div class="bg-center bg-no-repeat aspect-square bg-cover rounded-full size-10 shrink-0" style='background-image: url("https://lh3.googleusercontent.com/aida-public/AB6AXuCxe92kEf7gMHjbEHfZQu3F-p4XUO0nyA37zYAuOz7CiVXM_3hgmQ9gTI6zw7siePySKKolumdfXax7FjZ1tuLAnsb5rDYnZjw4LaKpR0MpYWUilv2DSX2VlCD416jAvXmMW3d3TA0MfMgLOkvyyvAqiNcFnqdLIk1LOdKh1Axylm3hUbhf-JtzopMhBhZ5WxEDvTgpGF0E65VLCr805vqY4iosbw4L8Qmm-sViAPSF8dXyszl2XldUnwHCnAakeX7o04PO1S6iwT_m");'></div>
            <div class="flex flex-1 flex-col gap-1 items-start">
                <p class="text-text-light-secondary dark:text-text-dark-secondary text-sm font-medium">StudyX Agent</p>
                <p class="text-base font-normal leading-normal rounded-xl rounded-bl-none px-4 py-3 bg-red-50 border border-red-200 text-red-600">
                    ❌ ${errorText}
                </p>
            </div>
        </div>
    `;
    messagesDiv.insertAdjacentHTML('beforeend', errorMsg);
    scrollToBottom();
}

// 🆕 智能滚动：只有用户在底部附近时才自动滚动
let userScrolledAway = false;
let scrollCheckTimeout = null;
let lastScrollTop = 0;
let isAutoScrolling = false;

/**
 * 🆕 检测内容类型
 * @param {object} content - 内容对象
 * @returns {string} - 内容类型
 */
function detectContentType(content) {
    if (!content) return 'unknown';
    
    if (content.questions && Array.isArray(content.questions)) {
        return 'quiz_set';
    } else if (content.concept && content.intuition) {
        return 'explanation';
    } else if (content.cards && Array.isArray(content.cards)) {
        return 'flashcard_set';
    } else if (content.components && Array.isArray(content.components)) {
        return 'learning_bundle';
    } else if (content.root && content.root.name) {
        return 'mindmap';
    } else if (content.structured_notes) {
        return 'notes';
    } else {
        return 'unknown';
    }
}

/**
 * 🆕 智能提取Thinking Summary（动态反映当前思考阶段）
 * 从完整的thinking内容中识别AI的思考阶段
 * 支持中英文混合的thinking内容
 * 
 * 策略：优先提取**最后出现**的动作，反映当前正在进行的思考阶段
 * 
 * @param {string} thinkingText - 完整的thinking内容
 * @returns {string} - 提取的summary（最多100个字符，支持换行）
 */
function extractThinkingSummary(thinkingText) {
    if (!thinkingText || thinkingText.trim().length === 0) {
        return '正在思考...';
    }
    
    const text = thinkingText.toLowerCase();
    
    // 🆕 英文模式匹配（Kimi的thinking通常是英文）
    // 注意：使用全局匹配，然后取最后一个，反映当前阶段
    const englishPatterns = [
        // "Let me..." / "I'll..." (最常见的阶段切换标志)
        { pattern: /(?:Let me|I'll)\s+(\w+)\s+([^.\n]{5,40})/g, template: (m) => `正在${translateAction(m[1])}${m[2].slice(0, 20)}...`, priority: 10 },
        
        // "I need to..." / "I should..." / "I will..."
        { pattern: /I (?:need|should|will) (?:to )?(\w+)\s+([^.\n]{5,40})/g, template: (m) => `正在${translateAction(m[1])}${m[2].slice(0, 20)}...`, priority: 9 },
        
        // "Now I..." (当前阶段)
        { pattern: /Now I (?:will|need to|should) (\w+)\s+([^.\n]{5,40})/g, template: (m) => `正在${translateAction(m[1])}${m[2].slice(0, 20)}...`, priority: 8 },
        
        // "I should follow the ... strategy"
        { pattern: /I should follow the "?([^"\n]{5,30})"? strategy/g, template: (m) => `应用策略：${m[1]}`, priority: 7 },
        
        // "This is a ... concept/question"
        { pattern: /This is a (\w+)\s+(concept|question|topic)/g, template: (m) => `识别为${m[1] === 'simple' ? '简单' : m[1] === 'complex' ? '复杂' : ''}${m[2] === 'concept' ? '概念' : '问题'}`, priority: 6 },
        
        // "The user wants to..." / "The user needs..." (优先级降低，只在开始时使用)
        { pattern: /The user wants (?:me )?to ([^.\n]{10,50})/g, template: (m) => `理解需求：${m[1].slice(0, 30)}...`, priority: 3 },
        { pattern: /The user (?:is asking|asks) (?:me )?to ([^.\n]{10,50})/g, template: (m) => `理解需求：${m[1].slice(0, 30)}...`, priority: 2 }
    ];
    
    // 收集所有匹配项，按位置排序
    let bestMatch = null;
    let bestPosition = -1;
    let bestPriority = -1;
    
    for (const {pattern, template, priority} of englishPatterns) {
        // 重置lastIndex
        pattern.lastIndex = 0;
        
        let match;
        while ((match = pattern.exec(thinkingText)) !== null) {
            const position = match.index;
            // 优先选择最后出现的高优先级匹配
            if (position > bestPosition || (position === bestPosition && priority > bestPriority)) {
                bestMatch = match;
                bestPosition = position;
                bestPriority = priority;
                
                // 保存template函数
                if (!bestMatch._template) {
                    bestMatch._template = template;
                }
            }
        }
    }
    
    // 如果找到匹配，使用最后一个（反映当前阶段）
    if (bestMatch && bestMatch._template) {
        try {
            const summary = bestMatch._template(bestMatch);
            if (summary && summary.length > 5) {
                return summary.slice(0, 100);  // 🔥 增加到100字符，减少截断
            }
        } catch (e) {
            console.warn('Summary extraction error:', e);
        }
    }
    
    // 🆕 通用英文动词检测（fallback：捕获任何未匹配的动作动词）
    const commonVerbs = [
        'analyzing', 'generating', 'creating', 'building', 'structuring', 'drafting',
        'explaining', 'understanding', 'identifying', 'determining', 'checking', 'verifying',
        'extracting', 'summarizing', 'organizing', 'designing', 'planning', 'thinking',
        'considering', 'evaluating', 'reviewing', 'preparing', 'forming', 'constructing',
        'developing', 'processing', 'formulating', 'arranging', 'assembling'
    ];
    
    // 查找最后出现的动词
    let lastVerbPosition = -1;
    let lastVerb = null;
    let lastVerbContext = '';
    
    for (const verb of commonVerbs) {
        // 查找 "...ing" 形式
        const verbPattern = new RegExp(`(${verb})\\s+([^.\\n]{5,40})`, 'gi');
        let match;
        verbPattern.lastIndex = 0;
        while ((match = verbPattern.exec(thinkingText)) !== null) {
            if (match.index > lastVerbPosition) {
                lastVerbPosition = match.index;
                lastVerb = match[1];
                lastVerbContext = match[2];
            }
        }
    }
    
    if (lastVerb) {
        const action = lastVerb.replace(/ing$/, 'e').replace(/ning$/, 'n'); // analyzing -> analyze
        return `正在${translateAction(action)}${lastVerbContext.slice(0, 20)}...`;
    }
    
    // 中文模式匹配
    const chineseActionWords = ['分析', '生成', '整理', '验证', '构建', '思考', '提取', '总结', '规划', '编写', '创建', '设计', '检查', '优化', '理解', '解释'];
    
    // 查找最后出现的中文动作词
    let lastChinesePosition = -1;
    let lastChineseMatch = null;
    
    for (const action of chineseActionWords) {
        const pattern = new RegExp(`(正在|需要|我正在|我需要)${action}[^。！？\\n]{0,30}`, 'g');
        let match;
        pattern.lastIndex = 0;
        while ((match = pattern.exec(thinkingText)) !== null) {
            if (match.index > lastChinesePosition) {
                lastChinesePosition = match.index;
                lastChineseMatch = match[0];
            }
        }
    }
    
    if (lastChineseMatch) {
        return lastChineseMatch.slice(0, 100);  // 🔥 增加到100字符，减少截断
    }
    
    // 🆕 提取最后一个有意义的句子（优先英文，因为thinking通常是英文）
    const allSentences = thinkingText.split(/[.。！？\n]/);
    
    // 从后往前找第一个有意义的句子
    for (let i = allSentences.length - 1; i >= 0; i--) {
        const sentence = allSentences[i].trim();
        if (sentence.length >= 15 && sentence.length <= 100) {
            // 如果是英文句子，尝试翻译关键动词
            if (/^[a-zA-Z]/.test(sentence)) {
                return `思考中：${sentence.slice(0, 80)}...`;  // 🔥 增加到80字符
            }
            // 如果是中文句子
            const chineseChars = sentence.match(/[\u4e00-\u9fa5]/g);
            if (chineseChars && chineseChars.length > 5) {
                return sentence.slice(0, 100) + (sentence.length > 100 ? '...' : '');  // 🔥 增加到100字符
            }
        }
    }
    
    // 最终fallback：智能截取（避免截断在单词中间）
    const finalText = thinkingText.trim();
    if (finalText.length <= 100) {  // 🔥 增加到100字符
        return finalText;
    }
    
    // 在100字符附近找一个空格或标点，避免截断单词
    let cutoff = 100;
    for (let i = 100; i < Math.min(120, finalText.length); i++) {
        if (/[\s,.;:!?。，；：！？]/.test(finalText[i])) {
            cutoff = i;
            break;
        }
    }
    
    return finalText.slice(0, cutoff).trim() + '...';
}

/**
 * 翻译英文动作词为中文（扩展版，支持更多动词）
 */
function translateAction(action) {
    const actionMap = {
        // 分析类
        'analyze': '分析', 'analyzes': '分析', 'analyzing': '分析',
        'evaluate': '评估', 'review': '审查', 'consider': '考虑',
        
        // 创建类
        'generate': '生成', 'create': '创建', 'build': '构建', 'construct': '构建',
        'structure': '构建', 'form': '形成', 'develop': '开发', 'design': '设计',
        
        // 编写类
        'draft': '编写', 'write': '编写', 'compose': '撰写',
        
        // 理解类
        'explain': '解释', 'understand': '理解', 'clarify': '澄清',
        
        // 识别类
        'identify': '识别', 'determine': '确定', 'recognize': '识别',
        
        // 验证类
        'check': '检查', 'verify': '验证', 'validate': '验证',
        
        // 处理类
        'extract': '提取', 'summarize': '总结', 'organize': '整理',
        'process': '处理', 'arrange': '安排', 'prepare': '准备',
        
        // 规划类
        'plan': '规划', 'think': '思考', 'formulate': '制定',
        
        // 其他
        'follow': '遵循', 'use': '使用', 'apply': '应用', 'assemble': '组装'
    };
    const normalized = action.toLowerCase().replace(/ing$/, '').replace(/es$/, 'e').replace(/s$/, '');
    return actionMap[normalized] || actionMap[action.toLowerCase()] || action;
}

function scrollToBottom() {
    const chatArea = document.getElementById('chatMessages');
    
    // 检测用户是否手动滚动到其他位置
    const isNearBottom = chatArea.scrollHeight - chatArea.scrollTop - chatArea.clientHeight < 100;
    
    // 只有当用户在底部附近时才自动滚动
    if (isNearBottom && !userScrolledAway) {
        isAutoScrolling = true;
        chatArea.scrollTop = chatArea.scrollHeight;
        // 短暂延迟后重置标志，避免误判
        setTimeout(() => { isAutoScrolling = false; }, 50);
    }
}

// 监听用户的滚动行为
document.addEventListener('DOMContentLoaded', () => {
    const chatArea = document.getElementById('chatMessages');
    
    chatArea.addEventListener('scroll', () => {
        // 如果是自动滚动触发的，忽略
        if (isAutoScrolling) {
            lastScrollTop = chatArea.scrollTop;
            return;
        }
        
        clearTimeout(scrollCheckTimeout);
        
        // 延迟检查，避免频繁触发
        scrollCheckTimeout = setTimeout(() => {
            const scrollTop = chatArea.scrollTop;
            const scrollHeight = chatArea.scrollHeight;
            const clientHeight = chatArea.clientHeight;
            const isNearBottom = scrollHeight - scrollTop - clientHeight < 100;
            
            // 检测用户是否主动向上滚动
            const userScrolledUp = scrollTop < lastScrollTop;
            
            if (userScrolledUp || !isNearBottom) {
                // 用户主动向上滚动，或者不在底部
                userScrolledAway = true;
                console.log('🛑 用户手动滚动，停止自动滚动');
            } else if (isNearBottom) {
                // 用户滚回底部
                userScrolledAway = false;
                console.log('✅ 用户返回底部，恢复自动滚动');
            }
            
            lastScrollTop = scrollTop;
        }, 100);
    });
});

// 新建聊天
function handleNewChat() {
    const messagesDiv = document.getElementById('chatMessages').querySelector('.flex.flex-col.gap-6');
    messagesDiv.innerHTML = `
        <div class="flex items-end gap-3 max-w-2xl">
            <div class="bg-center bg-no-repeat aspect-square bg-cover rounded-full size-10 shrink-0" style='background-image: url("https://lh3.googleusercontent.com/aida-public/AB6AXuCxe92kEf7gMHjbEHfZQu3F-p4XUO0nyA37zYAuOz7CiVXM_3hgmQ9gTI6zw7siePySKKolumdfXax7FjZ1tuLAnsb5rDYnZjw4LaKpR0MpYWUilv2DSX2VlCD416jAvXmMW3d3TA0MfMgLOkvyyvAqiNcFnqdLIk1LOdKh1Axylm3hUbhf-JtzopMhBhZ5WxEDvTgpGF0E65VLCr805vqY4iosbw4L8Qmm-sViAPSF8dXyszl2XldUnwHCnAakeX7o04PO1S6iwT_m");'></div>
            <div class="flex flex-1 flex-col gap-1 items-start">
                <p class="text-text-light-secondary dark:text-text-dark-secondary text-sm font-medium">StudyX Agent</p>
                <p class="text-base font-normal leading-normal rounded-xl rounded-bl-none px-4 py-3 bg-surface-light dark:bg-surface-dark border border-border-light dark:border-border-dark text-text-light-primary dark:text-text-dark-primary">
                    开始和 AI 学习助手对话吧！你可以尝试：
                    <br>• "给我几道微积分练习题"（数学）
                    <br>• "解释一下牛顿第二定律"（物理）
                    <br>• "什么是光合作用"（生物）
                    <br>• "帮我理解二战的起因"（历史）
                </p>
            </div>
        </div>
    `;
}

// ========================================
// 笔记编辑功能
// ========================================

// 切换编辑模式
function toggleEditMode(notesId) {
    const container = document.getElementById(`notes_${notesId}`);
    if (!container) return;
    
    const isEditing = container.classList.contains('editing-mode');
    
    if (isEditing) {
        exitEditMode(container);
    } else {
        enterEditMode(container);
    }
}

// 进入编辑模式
function enterEditMode(container) {
    container.classList.add('editing-mode');
    
    container.querySelector('.edit-btn').classList.add('hidden');
    container.querySelector('.save-btn').classList.remove('hidden');
    container.querySelector('.cancel-btn').classList.remove('hidden');
    
    container.querySelectorAll('[contenteditable]').forEach(el => {
        el.contentEditable = 'true';
        el.classList.add('editing', 'bg-yellow-50', 'dark:bg-yellow-900/20', 'px-2', 'py-1', 'rounded', 'border', 'border-yellow-300', 'dark:border-yellow-700');
    });
    
    container.querySelectorAll('.add-point-btn, .delete-point-btn').forEach(btn => {
        btn.classList.remove('hidden');
    });
    
    container.dataset.originalContent = container.innerHTML;
    console.log('✏️ 进入编辑模式');
}

// 退出编辑模式
function exitEditMode(container) {
    container.classList.remove('editing-mode');
    
    container.querySelector('.edit-btn').classList.remove('hidden');
    container.querySelector('.save-btn').classList.add('hidden');
    container.querySelector('.cancel-btn').classList.add('hidden');
    
    container.querySelectorAll('[contenteditable="true"]').forEach(el => {
        el.contentEditable = 'false';
        el.classList.remove('editing', 'bg-yellow-50', 'dark:bg-yellow-900/20', 'px-2', 'py-1', 'rounded', 'border', 'border-yellow-300', 'dark:border-yellow-700');
    });
    
    container.querySelectorAll('.add-point-btn, .delete-point-btn').forEach(btn => {
        btn.classList.add('hidden');
    });
    
    delete container.dataset.originalContent;
    console.log('👁️ 退出编辑模式');
}

// 保存笔记
async function saveNotes(notesId) {
    const container = document.getElementById(`notes_${notesId}`);
    if (!container) return;
    
    try {
        const title = container.querySelector('.editable-title').textContent.trim();
        const sections = [];
        
        container.querySelectorAll('.notebook-section').forEach(sectionEl => {
            const heading = sectionEl.querySelector('.section-heading').textContent.trim();
            const bullet_points = [];
            
            sectionEl.querySelectorAll('.bullet-point').forEach(pointEl => {
                const text = pointEl.textContent.trim();
                if (text) bullet_points.push(text);
            });
            
            if (heading && bullet_points.length > 0) {
                sections.push({ heading, bullet_points });
            }
        });
        
        const updatedNotes = {
            notes_id: notesId,
            structured_notes: { title, sections }
        };
        
        console.log('💾 保存笔记:', updatedNotes);
        
        // TODO: 发送到后端保存
        // await fetch(`${API_BASE}/api/notes/${notesId}`, {
        //     method: 'PUT',
        //     headers: { 'Content-Type': 'application/json' },
        //     body: JSON.stringify(updatedNotes)
        // });
        
        exitEditMode(container);
        showNotification('✅ 笔记已保存', 'success');
        
    } catch (error) {
        console.error('保存笔记失败:', error);
        showNotification('❌ 保存失败: ' + error.message, 'error');
    }
}

// 取消编辑
function cancelEdit(notesId) {
    const container = document.getElementById(`notes_${notesId}`);
    if (!container) return;
    
    if (container.dataset.originalContent) {
        container.innerHTML = container.dataset.originalContent;
    }
    
    console.log('🚫 取消编辑');
}

// 添加要点
function addBulletPoint(notesId, sectionIdx) {
    const container = document.getElementById(`notes_${notesId}`);
    if (!container) return;
    
    const section = container.querySelector(`[data-section-id="${sectionIdx}"]`);
    if (!section) return;
    
    const bulletList = section.querySelector('.bullet-list');
    const newPointIdx = bulletList.children.length;
    
    const newPoint = document.createElement('li');
    newPoint.className = 'flex items-start gap-3 group';
    newPoint.dataset.pointId = newPointIdx;
    newPoint.innerHTML = `
        <span class="text-blue-500 mt-1 text-lg">•</span>
        <span class="flex-1 text-base text-gray-700 dark:text-gray-300 leading-relaxed bullet-point editing bg-yellow-50 dark:bg-yellow-900/20 px-2 py-1 rounded border border-yellow-300 dark:border-yellow-700" contenteditable="true">新要点（点击编辑）</span>
        <button onclick="removeBulletPoint('${notesId}', ${sectionIdx}, ${newPointIdx})" class="delete-point-btn opacity-0 group-hover:opacity-100 text-red-400 hover:text-red-600 transition-opacity p-1">
            <span class="material-symbols-outlined text-sm">delete</span>
        </button>
    `;
    
    bulletList.appendChild(newPoint);
    
    const editableSpan = newPoint.querySelector('.bullet-point');
    editableSpan.focus();
    
    const range = document.createRange();
    range.selectNodeContents(editableSpan);
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
    
    console.log('➕ 添加新要点');
}

// 删除要点
function removeBulletPoint(notesId, sectionIdx, pointIdx) {
    const container = document.getElementById(`notes_${notesId}`);
    if (!container) return;
    
    const section = container.querySelector(`[data-section-id="${sectionIdx}"]`);
    if (!section) return;
    
    const point = section.querySelector(`[data-point-id="${pointIdx}"]`);
    if (!point) return;
    
    if (confirm('确定要删除这个要点吗？')) {
        point.remove();
        console.log('🗑️ 删除要点');
    }
}

// 显示通知
function showNotification(message, type = 'info') {
    const notification = document.createElement('div');
    notification.className = `fixed top-4 right-4 px-6 py-3 rounded-lg shadow-lg text-white z-50 transition-all ${
        type === 'success' ? 'bg-green-500' : 
        type === 'error' ? 'bg-red-500' : 
        'bg-blue-500'
    }`;
    notification.textContent = message;
    
    document.body.appendChild(notification);
    
    setTimeout(() => {
        notification.style.opacity = '0';
        setTimeout(() => notification.remove(), 300);
    }, 3000);
}

// ============= Learning History功能 =============

// 历史记录状态
let historyData = {
  artifacts: [],
  filteredArtifacts: [],
  currentFilter: 'all',
  searchTerm: '',
  page: 1,
  hasMore: true,
  isLoading: false
};

// 初始化历史记录功能
function initHistory() {
  const historyPanel = document.getElementById('historyPanel');
  const historyOverlay = document.getElementById('historyOverlay');
  const historyToggleBtn = document.getElementById('historyToggleBtn');
  const historyCloseBtn = document.getElementById('historyCloseBtn');
  const historySearch = document.getElementById('historySearch');
  
  // 打开面板
  historyToggleBtn.addEventListener('click', (e) => {
    e.preventDefault();
    openHistoryPanel();
  });
  
  // 关闭面板
  historyCloseBtn.addEventListener('click', closeHistoryPanel);
  historyOverlay.addEventListener('click', closeHistoryPanel);
  
  // 搜索
  historySearch.addEventListener('input', (e) => {
    historyData.searchTerm = e.target.value.toLowerCase();
    filterAndRenderHistory();
  });
  
  // 筛选按钮
  document.querySelectorAll('#historyPanel .filter-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
      document.querySelectorAll('#historyPanel .filter-btn').forEach(b => b.classList.remove('active'));
      e.target.classList.add('active');
      historyData.currentFilter = e.target.dataset.type;
      filterAndRenderHistory();
    });
  });
  
  console.log('✅ History initialized');
}

// 打开历史记录面板
async function openHistoryPanel() {
  const historyPanel = document.getElementById('historyPanel');
  const historyOverlay = document.getElementById('historyOverlay');
  
  historyPanel.classList.add('open');
  historyOverlay.classList.add('active');
  
  // 如果还没有加载过数据，则加载
  if (historyData.artifacts.length === 0 && !historyData.isLoading) {
    await loadHistory();
  }
}

// 关闭历史记录面板
function closeHistoryPanel() {
  const historyPanel = document.getElementById('historyPanel');
  const historyOverlay = document.getElementById('historyOverlay');
  
  historyPanel.classList.remove('open');
  historyOverlay.classList.remove('active');
}

// 加载历史记录
async function loadHistory() {
  if (historyData.isLoading || !historyData.hasMore) return;
  
  historyData.isLoading = true;
  
  try {
    const response = await fetch(
      `${API_BASE}/api/sessions/${SESSION_ID}/artifacts?page=${historyData.page}&limit=50`
    );
    
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    
    const data = await response.json();
    
    // 合并新数据
    historyData.artifacts = [...historyData.artifacts, ...data.artifacts];
    historyData.hasMore = data.has_more;
    historyData.page += 1;
    
    console.log(`📚 Loaded ${data.artifacts.length} artifacts, total: ${historyData.artifacts.length}`);
    
    filterAndRenderHistory();
  } catch (error) {
    console.error('❌ Failed to load history:', error);
    showHistoryError('Failed to load history. Please try again.');
  } finally {
    historyData.isLoading = false;
  }
}

// 筛选并渲染历史记录
function filterAndRenderHistory() {
  let filtered = historyData.artifacts;
  
  // 按类型筛选
  if (historyData.currentFilter !== 'all') {
    filtered = filtered.filter(item => item.artifact_type === historyData.currentFilter);
  }
  
  // 按搜索词筛选
  if (historyData.searchTerm) {
    filtered = filtered.filter(item => 
      item.topic.toLowerCase().includes(historyData.searchTerm) ||
      item.summary.toLowerCase().includes(historyData.searchTerm)
    );
  }
  
  historyData.filteredArtifacts = filtered;
  renderHistory();
}

// 渲染历史记录
function renderHistory() {
  const timeline = document.getElementById('historyTimeline');
  
  // 空状态
  if (historyData.artifacts.length === 0 && !historyData.isLoading) {
    timeline.innerHTML = `
      <div class="empty-state">
        <div class="empty-state-icon">📚</div>
        <p class="text-lg font-medium mb-2">No Learning History Yet</p>
        <p class="text-sm opacity-70">Start learning to see your history here!</p>
      </div>
    `;
    return;
  }
  
  // 无搜索结果
  if (historyData.filteredArtifacts.length === 0 && !historyData.isLoading) {
    timeline.innerHTML = `
      <div class="empty-state">
        <div class="empty-state-icon">🔍</div>
        <p class="text-lg font-medium mb-2">No Results Found</p>
        <p class="text-sm opacity-70">Try a different search term or filter</p>
      </div>
    `;
    return;
  }
  
  // 按日期分组
  const grouped = groupByDate(historyData.filteredArtifacts);
  
  // 生成 HTML
  let html = '';
  for (const [label, items] of Object.entries(grouped)) {
    html += `
      <div class="date-group">
        <div class="date-label">${label}</div>
        <div class="history-items">
          ${items.map(item => renderHistoryItem(item)).join('')}
        </div>
      </div>
    `;
  }
  
  // 加载更多按钮
  if (historyData.hasMore && historyData.filteredArtifacts.length > 0) {
    html += `
      <div class="load-more">
        <button onclick="loadHistory()">Load More...</button>
      </div>
    `;
  }
  
  timeline.innerHTML = html;
}

// 渲染单条历史记录
function renderHistoryItem(item) {
  const icon = getArtifactIcon(item.artifact_type);
  const time = formatTime(item.timestamp);
  const count = getArtifactCount(item);
  
  return `
    <div class="history-item" onclick="viewArtifact('${item.id}')">
      <div class="item-icon">${icon}</div>
      <div class="item-content">
        <div class="item-title">${escapeHtml(item.topic)}</div>
        <div class="item-meta">
          <span class="item-time">${time}</span>
          ${count ? `<span class="item-count">${count}</span>` : ''}
        </div>
      </div>
    </div>
  `;
}

// 查看历史记录（回溯）
async function viewArtifact(artifactId) {
  try {
    console.log(`📖 Viewing artifact: ${artifactId}`);
    
    // 从本地查找
    const artifact = historyData.artifacts.find(a => a.id === artifactId);
    
    if (!artifact) {
      console.error('Artifact not found');
      return;
    }
    
    // 关闭历史面板
    closeHistoryPanel();
    
    // 在 Chat 中添加回溯标签
    const timestamp = formatDateTime(artifact.timestamp);
    addSystemMessage(`🔙 [回溯] ${timestamp}`);
    
    // 根据类型渲染内容
    const messageData = {
      content_type: artifact.artifact_type,
      response_content: artifact.content
    };
    
    addAgentMessage(messageData);
    
    // 添加提示
    addSystemMessage('💡 你可以基于此内容继续对话，例如："再出3道类似的题"');
    
    console.log('✅ Artifact displayed');
    
  } catch (error) {
    console.error('❌ Failed to view artifact:', error);
    addErrorMessage('Failed to load artifact. Please try again.');
  }
}

// 添加系统消息
function addSystemMessage(text) {
  const messagesDiv = document.getElementById('chatMessages').querySelector('.flex.flex-col.gap-6');
  const systemMsg = `
    <div class="flex items-center justify-center my-4">
      <div class="px-4 py-2 rounded-full bg-primary/10 text-primary text-sm font-medium">
        ${text}
      </div>
    </div>
  `;
  messagesDiv.insertAdjacentHTML('beforeend', systemMsg);
  scrollToBottom();
}

// 显示历史记录错误
function showHistoryError(message) {
  const timeline = document.getElementById('historyTimeline');
  timeline.innerHTML = `
    <div class="empty-state">
      <div class="empty-state-icon">❌</div>
      <p class="text-lg font-medium mb-2">Error</p>
      <p class="text-sm opacity-70">${message}</p>
    </div>
  `;
}

// ============= 辅助函数 =============

// 按日期分组
function groupByDate(artifacts) {
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterday = new Date(today - 86400000);
  const thisWeek = new Date(today - 7 * 86400000);
  
  const groups = {
    '📅 今天': [],
    '📅 昨天': [],
    '📅 本周': [],
    '📅 更早': []
  };
  
  artifacts.forEach(item => {
    const date = new Date(item.timestamp);
    if (date >= today) {
      groups['📅 今天'].push(item);
    } else if (date >= yesterday) {
      groups['📅 昨天'].push(item);
    } else if (date >= thisWeek) {
      groups['📅 本周'].push(item);
    } else {
      groups['📅 更早'].push(item);
    }
  });
  
  // 移除空分组
  Object.keys(groups).forEach(key => {
    if (groups[key].length === 0) {
      delete groups[key];
    }
  });
  
  return groups;
}

// 获取 artifact 图标
function getArtifactIcon(type) {
  const icons = {
    'quiz_set': '❓',
    'flashcard_set': '🎴',
    'notes': '📝',
    'explanation': '💡',
    'mindmap': '🗺️',
    'learning_bundle': '📦'
  };
  return icons[type] || '📄';
}

// 获取 artifact 数量
function getArtifactCount(item) {
  if (item.artifact_type === 'quiz_set' && item.content.questions) {
    return `${item.content.questions.length} 题`;
  } else if (item.artifact_type === 'flashcard_set' && item.content.cards) {
    return `${item.content.cards.length} 卡`;
  }
  return null;
}

// 格式化时间
function formatTime(timestamp) {
  const date = new Date(timestamp);
  return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
}

function formatDateTime(timestamp) {
  const date = new Date(timestamp);
  return date.toLocaleString('zh-CN');
}

// HTML 转义
function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

// ============= LaTeX渲染辅助函数 =============
function renderMathInContent(element) {
    if (typeof renderMathInElement !== 'undefined') {
        try {
            renderMathInElement(element, {
                delimiters: [
                    {left: '$$', right: '$$', display: true},
                    {left: '$', right: '$', display: false},
                    {left: '\\[', right: '\\]', display: true},
                    {left: '\\(', right: '\\)', display: false}
                ],
                throwOnError: false
            });
        } catch (e) {
            console.warn('LaTeX rendering error:', e);
        }
    }
}

// ============= 页面加载时初始化 =============
document.addEventListener('DOMContentLoaded', async () => {
  // 初始化用户（必须先完成）
  await initializeUser();
  console.log('✅ User initialized');
  
  // 初始化历史记录
  initHistory();
  console.log('🎉 Page loaded and history initialized');
  
  // 🆕 初始化KaTeX自动渲染
  if (typeof renderMathInElement !== 'undefined') {
      // 监听DOM变化，自动渲染LaTeX
      const observer = new MutationObserver((mutations) => {
          mutations.forEach((mutation) => {
              mutation.addedNodes.forEach((node) => {
                  if (node.nodeType === 1) { // Element node
                      // 渲染thinking内容
                      if (node.classList && node.classList.contains('thinking-content')) {
                          renderMathInContent(node);
                      }
                      // 渲染所有新添加的内容
                      const thinkingElements = node.querySelectorAll && node.querySelectorAll('.thinking-content, .prose');
                      if (thinkingElements) {
                          thinkingElements.forEach(el => renderMathInContent(el));
                      }
                  }
              });
          });
      });
      
      observer.observe(document.getElementById('chatMessages'), {
          childList: true,
          subtree: true
      });
  }
});

