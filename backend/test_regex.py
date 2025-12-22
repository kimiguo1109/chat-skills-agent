import re

# 修复后的正则
patterns = [
    r'第[一二三四五六七八九十\d]+道?题',
    r'第[一二三四五六七八九十\d]+张[闪]?卡片?',
]

test_cases = [
    '把第二道题帮我详细解释一下',
    '把第一张闪卡出一道题',
    '解释一下第三题',
    '第2道题是什么意思',
]

print("=== 正则表达式测试 ===\n")
for msg in test_cases:
    cleaned = msg
    for pattern in patterns:
        cleaned = re.sub(pattern, '', cleaned)
    print(f'原消息: {msg}')
    print(f'清理后: {cleaned}')
    print()

