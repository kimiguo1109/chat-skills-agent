"""
简单测试 Kimi API 连接
"""
from openai import OpenAI

# 直接使用用户提供的配置
client = OpenAI(
    api_key="sk_RVzD0ExdrmLuQIcvC-UbUekNsbft0dVPiOq5Nh-1Xro",
    base_url="https://api.novita.ai/openai"
)

try:
    print("🧪 测试 Kimi API 连接...")
    print(f"📍 Base URL: https://api.novita.ai/openai")
    print(f"🔑 API Key: sk-897e...38dc")
    print(f"🤖 Model: moonshotai/kimi-k2-thinking")
    print()
    
    response = client.chat.completions.create(
        model="moonshotai/kimi-k2-thinking",
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello, how are you?"}
        ],
        max_tokens=100,
        temperature=0.7
    )
    
    print("✅ 连接成功！")
    print(f"📝 Response:")
    print(response.choices[0].message.content)
    print()
    print(f"📊 Usage:")
    print(f"  - Prompt tokens: {response.usage.prompt_tokens}")
    print(f"  - Completion tokens: {response.usage.completion_tokens}")
    print(f"  - Total tokens: {response.usage.total_tokens}")

except Exception as e:
    print(f"❌ 错误: {e}")
    import traceback
    traceback.print_exc()

