#!/usr/bin/env python3
"""
测试脚本：真思考 vs 伪思考 (流式版本)

使用流式 API 来获得实时反馈，避免长时间等待
"""
import asyncio
import httpx
import json
from datetime import datetime

# 配置
BASE_URL = "http://localhost:8088"
API_ENDPOINT = f"{BASE_URL}/api/agent/chat-stream"  # 使用流式端点
USER_ID = "test_thinking_stream"
TIMEOUT = 480.0


def print_header(title):
    """打印美化的标题"""
    print("\n" + "="*80)
    print(f"  {title}")
    print("="*80 + "\n")


def print_section(title):
    """打印小节标题"""
    print(f"\n{'─'*60}")
    print(f"  {title}")
    print(f"{'─'*60}\n")


async def send_message_stream(message: str, session_id: str = None) -> dict:
    """发送消息到 Agent (流式)"""
    print(f"📤 发送: {message}")
    
    # 如果没有 session_id，生成一个默认的
    if not session_id:
        session_id = f"thinking_stream_{int(datetime.now().timestamp())}"
    
    payload = {
        "message": message,
        "user_id": USER_ID,
        "session_id": session_id
    }
    
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        try:
            # 🌊 流式请求
            thinking_chars = 0
            content_chars = 0
            first_chunk_time = None
            start_time = datetime.now()
            
            async with client.stream("POST", API_ENDPOINT, json=payload) as response:
                response.raise_for_status()
                
                print(f"🌊 开始接收流式响应...")
                
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    
                    # 解析 SSE 格式
                    if line.startswith("data: "):
                        data_str = line[6:]  # 去掉 "data: " 前缀
                        
                        try:
                            chunk = json.loads(data_str)
                            chunk_type = chunk.get("type")
                            
                            if first_chunk_time is None:
                                first_chunk_time = datetime.now()
                                elapsed = (first_chunk_time - start_time).total_seconds()
                                print(f"✅ 首个 chunk 到达 ({elapsed:.1f}s)")
                            
                            if chunk_type == "status":
                                msg = chunk.get("message", "")
                                print(f"📊 {msg}")
                            
                            elif chunk_type == "thinking":
                                text = chunk.get("text", "")
                                thinking_chars += len(text)
                                if thinking_chars % 100 == 0:  # 每100字符打印一次
                                    print(f"🧠 Thinking... ({thinking_chars} chars)")
                            
                            elif chunk_type == "content":
                                text = chunk.get("text", "")
                                content_chars += len(text)
                                if content_chars % 100 == 0:  # 每100字符打印一次
                                    print(f"📝 Content... ({content_chars} chars)")
                            
                            elif chunk_type == "done":
                                end_time = datetime.now()
                                total_elapsed = (end_time - start_time).total_seconds()
                                print(f"✅ 响应完成 (总耗时: {total_elapsed:.1f}s)")
                                print(f"   Thinking: {thinking_chars} chars")
                                print(f"   Content: {content_chars} chars")
                                
                                # 提取最终数据
                                content = chunk.get("content", {})
                                # 处理 content 可能是字符串的情况
                                if isinstance(content, dict):
                                    usage = content.get("_usage", {})
                                else:
                                    usage = {}
                                
                                return {
                                    "session_id": session_id,
                                    "thinking_chars": thinking_chars,
                                    "content_chars": content_chars,
                                    "total_time": total_elapsed,
                                    "usage": usage
                                }
                            
                            elif chunk_type == "error":
                                error_msg = chunk.get("message", "Unknown error")
                                print(f"❌ 错误: {error_msg}")
                                return None
                        
                        except json.JSONDecodeError as e:
                            print(f"⚠️  JSON 解析失败: {e}")
                            continue
            
            return None
        
        except httpx.ReadTimeout:
            print(f"⏱️  请求超时 (>{TIMEOUT}s)")
            return None
        except Exception as e:
            print(f"❌ 请求失败: {e}")
            return None


async def test_thinking_modes_stream():
    """测试真思考 vs 伪思考 (流式)"""
    print_header("🌊 真思考 vs ⚡ 伪思考 - 流式测试")
    
    session_id = None
    results = []
    
    # ==================== Scenario 1: 全新 Topic ====================
    print_section("场景 1: 全新 Topic（应触发真思考 🧠）")
    print("📌 预期: Kimi k2-thinking (流式)")
    print("📌 优势: 实时看到 thinking 和 content 生成\n")
    
    resp1 = await send_message_stream("讲解一下光合作用", session_id)
    if resp1:
        session_id = resp1["session_id"]
        results.append({
            "scenario": "全新 Topic（光合作用）",
            "expected_mode": "真思考",
            "thinking_chars": resp1["thinking_chars"],
            "content_chars": resp1["content_chars"],
            "time": resp1["total_time"]
        })
        print(f"\n💾 Session ID: {session_id}")
    
    await asyncio.sleep(2)
    
    # ==================== Scenario 2: Follow-up ====================
    print_section("场景 2: Follow-up 问题（应触发伪思考 ⚡）")
    print("📌 预期: Gemini 2.0 Flash Exp (流式)")
    print("📌 优势: 更快的响应，更低的延迟\n")
    
    resp2 = await send_message_stream("生成3道关于光合作用的题目", session_id)
    if resp2:
        results.append({
            "scenario": "Follow-up（光合作用题目）",
            "expected_mode": "伪思考",
            "thinking_chars": resp2["thinking_chars"],
            "content_chars": resp2["content_chars"],
            "time": resp2["total_time"]
        })
    
    # ==================== 结果汇总 ====================
    print_header("📊 测试结果汇总")
    
    print(f"{'场景':<25} | {'预期模式':<10} | {'Thinking':<12} | {'Content':<12} | {'耗时':>8}")
    print("─" * 90)
    
    for r in results:
        print(f"{r['scenario']:<25} | {r['expected_mode']:<10} | {r['thinking_chars']:<12} | {r['content_chars']:<12} | {r['time']:>7.1f}s")
    
    print("\n")
    
    # ==================== 验证逻辑 ====================
    print_section("🔍 验证结果")
    
    print(f"✅ 完成 {len(results)} 个场景测试")
    print(f"\n💡 流式 API 的优势:")
    print(f"   • 实时反馈，无需等待整个响应")
    print(f"   • 可以看到 thinking 过程")
    print(f"   • 更好的用户体验")
    print(f"\n💡 查看 backend.log 确认模型选择:")
    print(f"   - 真思考: '🧠 Using Real Thinking (Kimi)'")
    print(f"   - 伪思考: '⚡ Using Fake Thinking (Gemini)'")


if __name__ == "__main__":
    asyncio.run(test_thinking_modes_stream())

