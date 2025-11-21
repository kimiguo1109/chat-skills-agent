#!/usr/bin/env python3
"""
测试上传现有的 MD 文件到 S3
"""
import sys
import os
import asyncio

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.core.s3_storage import S3StorageManager
from pathlib import Path

async def main():
    print("=" * 80)
    print("🔍 测试上传现有 MD 文件到 S3")
    print("=" * 80)
    
    # 1. 初始化 S3
    s3_manager = S3StorageManager()
    
    if not s3_manager.is_available():
        print("❌ S3 不可用")
        return
    
    print(f"✅ S3 可用: {s3_manager.bucket}")
    
    # 2. 找到本地 MD 文件
    artifacts_dir = Path(__file__).parent.parent / "artifacts"
    
    users = ["user_kimi", "user_alex"]
    
    for user in users:
        user_dir = artifacts_dir / user
        if not user_dir.exists():
            print(f"\n⚠️  {user} 目录不存在")
            continue
        
        print(f"\n📁 处理 {user}:")
        
        # 找到所有 MD 文件
        md_files = list(user_dir.glob("*.md"))
        
        if not md_files:
            print(f"   ⚠️  没有 MD 文件")
            continue
        
        for md_file in md_files:
            print(f"   📄 {md_file.name}")
            
            # 读取内容
            content = md_file.read_text(encoding='utf-8')
            
            # 上传到 S3 (路径: user_xxx/session_xxx.md)
            s3_key = f"{user}/{md_file.name}"
            
            try:
                result = s3_manager.save(
                    s3_key,
                    content,
                    content_type="text/markdown"
                )
                
                if result:
                    print(f"      ✅ 上传成功: {result}")
                else:
                    print(f"      ❌ 上传失败")
            
            except Exception as e:
                print(f"      ❌ 上传异常: {e}")
    
    print("\n" + "=" * 80)
    print("完成")
    print("=" * 80)

if __name__ == "__main__":
    asyncio.run(main())

