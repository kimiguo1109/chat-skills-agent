"""测试JSON解析"""
import asyncio
import json
from app.core.intent_router import IntentRouter
from app.core.skill_orchestrator import SkillOrchestrator
from app.dependencies import get_memory_manager, get_gemini_client

async def main():
    gemini_client = get_gemini_client()
    memory_manager = get_memory_manager()
    orchestrator = SkillOrchestrator(
        gemini_client=gemini_client,
        memory_manager=memory_manager
    )
    intent_router = IntentRouter(gemini_client=gemini_client)
    
    user_message = "给我5道光合作用的题"
    intent_results = await intent_router.parse(user_message)
    intent_result = intent_results[0]
    
    full_content = ""
    
    async for event in orchestrator.execute_stream(
        intent_result=intent_result,
        user_id="test-user",
        session_id="test-session"
    ):
        if event.get('type') == 'content':
            full_content += event.get('text', '')
        elif event.get('type') == 'done':
            print(f"完整content长度: {len(full_content)}")
            print(f"\n前200字符:")
            print(full_content[:200])
            print(f"\n后200字符:")
            print(full_content[-200:])
            
            # 尝试解析
            try:
                parsed = json.loads(full_content)
                print(f"\n✅ JSON解析成功！")
                print(f"题目数: {len(parsed.get('questions', []))}")
            except json.JSONDecodeError as e:
                print(f"\n❌ JSON解析失败: {e}")
                # 尝试提取JSON（去除markdown）
                if "```json" in full_content:
                    json_str = full_content.split("```json")[1].split("```")[0].strip()
                    try:
                        parsed = json.loads(json_str)
                        print(f"✅ 提取后解析成功！")
                        print(f"题目数: {len(parsed.get('questions', []))}")
                    except:
                        print(f"❌ 提取后仍失败")

asyncio.run(main())
