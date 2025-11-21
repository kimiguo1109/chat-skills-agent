#!/usr/bin/env python3
"""
诊断 S3 MD 文件上传问题
"""
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.core.s3_storage import S3StorageManager
from app.config import settings
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def main():
    print("=" * 80)
    print("🔍 S3 MD 上传诊断")
    print("=" * 80)
    
    # 1. 检查配置
    print("\n1️⃣ 检查 S3 配置:")
    print(f"   USE_S3_STORAGE: {settings.USE_S3_STORAGE}")
    print(f"   AWS_S3_BUCKET: {settings.AWS_S3_BUCKET}")
    print(f"   AWS_ACCESS_KEY_ID: {'✅ 已设置' if settings.AWS_ACCESS_KEY_ID else '❌ 未设置'}")
    print(f"   AWS_SECRET_ACCESS_KEY: {'✅ 已设置' if settings.AWS_SECRET_ACCESS_KEY else '❌ 未设置'}")
    print(f"   AWS_REGION: {settings.AWS_REGION}")
    
    # 2. 初始化 S3 Manager
    print("\n2️⃣ 初始化 S3StorageManager:")
    s3_manager = S3StorageManager()
    print(f"   s3_client: {'✅ 已初始化' if s3_manager.s3_client else '❌ 未初始化'}")
    print(f"   bucket: {s3_manager.bucket}")
    print(f"   is_available: {s3_manager.is_available()}")
    
    # 3. 测试上传 MD 文件
    if s3_manager.is_available():
        print("\n3️⃣ 测试上传 MD 文件:")
        test_content = """# Test Session - 2025-11-21

**User**: test_user  
**Session ID**: test_session  

## Turn 1

### 👤 User Query
测试问题

### 🤖 Agent Response
测试回答
"""
        
        test_key = "user_test/test_session.md"
        try:
            result = s3_manager.save(
                test_key,
                test_content,
                content_type="text/markdown"
            )
            
            if result:
                print(f"   ✅ 上传成功！")
                print(f"   S3 URI: {result}")
                
                # 4. 验证文件存在
                print("\n4️⃣ 验证上传的文件:")
                try:
                    response = s3_manager.s3_client.get_object(
                        Bucket=s3_manager.bucket,
                        Key=test_key
                    )
                    loaded_content = response['Body'].read().decode('utf-8')
                    print(f"   ✅ 文件可以正常读取")
                    print(f"   内容长度: {len(loaded_content)} bytes")
                except Exception as e:
                    print(f"   ❌ 无法读取上传的文件: {e}")
                
                # 5. 清理测试文件
                print("\n5️⃣ 清理测试文件:")
                try:
                    s3_manager.s3_client.delete_object(
                        Bucket=s3_manager.bucket,
                        Key=test_key
                    )
                    print(f"   ✅ 测试文件已删除")
                except Exception as e:
                    print(f"   ⚠️  清理失败: {e}")
            else:
                print(f"   ❌ 上传失败（返回 None）")
        
        except Exception as e:
            print(f"   ❌ 上传异常: {e}")
            import traceback
            traceback.print_exc()
    else:
        print("\n3️⃣ ⚠️ S3 不可用，跳过测试")
    
    # 6. 检查本地 MD 文件
    print("\n6️⃣ 检查本地 artifacts 目录:")
    artifacts_dir = os.path.join(os.path.dirname(__file__), '..', 'artifacts')
    if os.path.exists(artifacts_dir):
        print(f"   📁 artifacts 目录存在")
        for user_dir in os.listdir(artifacts_dir):
            user_path = os.path.join(artifacts_dir, user_dir)
            if os.path.isdir(user_path):
                print(f"\n   👤 {user_dir}:")
                md_files = [f for f in os.listdir(user_path) if f.endswith('.md')]
                if md_files:
                    for md_file in md_files:
                        file_path = os.path.join(user_path, md_file)
                        file_size = os.path.getsize(file_path)
                        print(f"      📄 {md_file} ({file_size} bytes)")
                else:
                    print(f"      ⚠️  无 MD 文件")
    else:
        print(f"   ❌ artifacts 目录不存在")
    
    print("\n" + "=" * 80)
    print("诊断完成")
    print("=" * 80)

if __name__ == "__main__":
    main()

