#!/usr/bin/env python3
"""
清理测试数据
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import boto3
import shutil
from pathlib import Path
from app.core.config import settings

def cleanup_test_data():
    print("\n" + "="*80)
    print("🗑️  Cleaning Up Test Data")
    print("="*80)
    
    # 1. 清理本地 memory_storage
    print("\n📂 Cleaning local memory_storage...")
    memory_storage_dir = Path(settings.MEMORY_STORAGE_DIR)
    
    if memory_storage_dir.exists():
        test_files = [
            'user_kimi_session_*.json',
            'user_alex_session_*.json',
        ]
        
        deleted_count = 0
        for pattern in test_files:
            for file_path in memory_storage_dir.glob(pattern):
                print(f"   🗑️  Deleting: {file_path.name}")
                file_path.unlink()
                deleted_count += 1
        
        if deleted_count > 0:
            print(f"   ✅ Deleted {deleted_count} session file(s)")
        else:
            print(f"   📭 No test session files found")
    else:
        print(f"   📭 Memory storage directory not found: {memory_storage_dir}")
    
    # 2. 清理本地 artifacts
    print("\n📦 Cleaning local artifacts...")
    artifacts_dir = Path(settings.ARTIFACT_STORAGE_DIR)
    
    if artifacts_dir.exists():
        for user_id in ['user_kimi', 'user_alex']:
            user_dir = artifacts_dir / user_id
            if user_dir.exists():
                print(f"   🗑️  Deleting directory: {user_dir}")
                shutil.rmtree(user_dir)
                print(f"   ✅ Deleted artifacts for {user_id}")
            else:
                print(f"   📭 No artifacts for {user_id}")
    else:
        print(f"   📭 Artifacts directory not found: {artifacts_dir}")
    
    # 3. 清理 S3（如果启用）
    if settings.USE_S3_STORAGE:
        print("\n☁️  Cleaning S3 storage...")
        try:
            s3 = boto3.client('s3')
            bucket = settings.AWS_S3_BUCKET
            artifact_folder = settings.S3_ARTIFACT_FOLDER
            
            deleted_total = 0
            for user_id in ['user_kimi', 'user_alex']:
                prefix = f"{artifact_folder}/{user_id}/"
                
                response = s3.list_objects_v2(Bucket=bucket, Prefix=prefix)
                objects = response.get('Contents', [])
                
                if objects:
                    print(f"   🗑️  Deleting {len(objects)} object(s) for {user_id}...")
                    for obj in objects:
                        s3.delete_object(Bucket=bucket, Key=obj['Key'])
                        print(f"      - {obj['Key']}")
                        deleted_total += 1
                    print(f"   ✅ Deleted {len(objects)} object(s) for {user_id}")
                else:
                    print(f"   📭 No S3 objects for {user_id}")
            
            if deleted_total > 0:
                print(f"   ✅ Total S3 objects deleted: {deleted_total}")
        except Exception as e:
            print(f"   ❌ Error cleaning S3: {e}")
    else:
        print("\n☁️  S3 storage not enabled, skipping...")
    
    print("\n" + "="*80)
    print("✅ Cleanup Complete")
    print("="*80)
    print("\n💡 Tip: You can now start fresh testing with clean data\n")

if __name__ == "__main__":
    cleanup_test_data()

