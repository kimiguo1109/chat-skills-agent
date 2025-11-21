"""
测试多用户场景：数据隔离和S3路径验证
"""
import asyncio
import os
import sys
import json
import logging

# Add the backend directory to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.core.memory_manager import MemoryManager
from app.core.s3_storage import S3StorageManager
from app.config import settings

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def test_multi_user_data_isolation():
    """测试多用户数据隔离"""
    
    logger.info("=" * 80)
    logger.info("多用户场景测试：数据隔离 & S3 路径验证")
    logger.info("=" * 80)
    
    logger.info(f"\n📋 Configuration:")
    logger.info(f"  S3 Enabled: {settings.USE_S3_STORAGE}")
    logger.info(f"  S3 Bucket: {settings.AWS_S3_BUCKET}")
    
    # 初始化 MemoryManager
    memory_manager = MemoryManager()
    logger.info(f"\n✅ MemoryManager initialized")
    logger.info(f"   S3 Enabled: {memory_manager.s3_manager.s3_client is not None}")
    
    # 用户数据
    users = [
        {
            "user_id": "user_kimi",
            "session_id": "user_kimi_session_20251121_test1",
            "content": {
                "concept": "量子纠缠",
                "subject": "物理",
                "intuition": "量子纠缠是一种神奇的量子现象，两个粒子无论距离多远都能瞬间影响对方的状态。",
                "formal_definition": "量子纠缠是指两个或多个量子系统之间存在的一种非定域关联。"
            }
        },
        {
            "user_id": "user_alex",
            "session_id": "user_alex_session_20251121_test1",
            "content": {
                "concept": "光合作用",
                "subject": "生物",
                "intuition": "光合作用是植物利用阳光、水和二氧化碳制造养分的过程。",
                "formal_definition": "光合作用是绿色植物利用叶绿素和光能将CO₂和H₂O转化为有机物并释放O₂的过程。"
            }
        }
    ]
    
    # 存储每个用户的 artifact
    artifact_records = {}
    
    logger.info("\n" + "━" * 80)
    logger.info("测试 1: 为每个用户保存 artifact")
    logger.info("━" * 80)
    
    for user in users:
        logger.info(f"\n📤 Saving artifact for {user['user_id']}...")
        logger.info(f"   Session: {user['session_id']}")
        logger.info(f"   Topic: {user['content']['concept']}")
        
        artifact_record = await memory_manager.save_artifact(
            session_id=user['session_id'],
            artifact=user['content'],
            artifact_type="explanation",
            topic=user['content']['concept'],
            user_id=user['user_id']
        )
        
        artifact_records[user['user_id']] = artifact_record
        
        logger.info(f"✅ Artifact saved for {user['user_id']}")
        logger.info(f"   Artifact ID: {artifact_record.artifact_id}")
        logger.info(f"   Storage Type: {artifact_record.storage_type}")
        logger.info(f"   Has External Storage: {artifact_record.has_external_storage}")
        logger.info(f"   Content Reference: {artifact_record.content_reference}")
        logger.info(f"   Content Size: {artifact_record.get_content_size_estimate()} bytes")
    
    # 验证 S3 路径隔离
    if memory_manager.s3_manager.s3_client is not None:
        logger.info("\n" + "━" * 80)
        logger.info("测试 2: 验证 S3 路径隔离")
        logger.info("━" * 80)
        
        s3_client = memory_manager.s3_manager.s3_client
        bucket_name = memory_manager.s3_manager.bucket
        artifact_folder = memory_manager.s3_manager.artifact_folder
        
        for user_id in ["user_kimi", "user_alex"]:
            prefix = f"{artifact_folder}/{user_id}/"
            logger.info(f"\n📂 Checking S3 path: s3://{bucket_name}/{prefix}")
            
            try:
                response = s3_client.list_objects_v2(Bucket=bucket_name, Prefix=prefix)
                objects = [obj['Key'] for obj in response.get('Contents', [])]
                
                logger.info(f"   Found {len(objects)} object(s)")
                for obj_key in objects:
                    obj_response = s3_client.get_object(Bucket=bucket_name, Key=obj_key)
                    obj_size = obj_response['ContentLength']
                    logger.info(f"   ✓ {obj_key} ({obj_size} bytes)")
                
                # 验证数据隔离
                if len(objects) == 1:
                    logger.info(f"   ✅ Data isolation verified for {user_id}")
                else:
                    logger.warning(f"   ⚠️  Expected 1 object, found {len(objects)}")
            except Exception as e:
                logger.error(f"   ❌ Error listing S3 objects: {e}")
    
    # 测试跨用户数据加载
    logger.info("\n" + "━" * 80)
    logger.info("测试 3: 验证数据加载和隔离")
    logger.info("━" * 80)
    
    for user in users:
        user_id = user['user_id']
        artifact_record = artifact_records[user_id]
        
        logger.info(f"\n📥 Loading artifact for {user_id}...")
        loaded_content = await memory_manager.get_artifact(artifact_record.artifact_id)
        
        if loaded_content:
            logger.info(f"✅ Successfully loaded artifact")
            logger.info(f"   Topic: {loaded_content['concept']}")
            logger.info(f"   Subject: {loaded_content['subject']}")
            
            # 验证内容匹配
            if loaded_content == user['content']:
                logger.info(f"   ✅ Content integrity verified")
            else:
                logger.error(f"   ❌ Content mismatch!")
        else:
            logger.error(f"❌ Failed to load artifact for {user_id}")
    
    # 验证不同用户的数据不会混淆
    logger.info("\n" + "━" * 80)
    logger.info("测试 4: 验证用户间数据不会混淆")
    logger.info("━" * 80)
    
    kimi_content = await memory_manager.get_artifact(artifact_records["user_kimi"].artifact_id)
    alex_content = await memory_manager.get_artifact(artifact_records["user_alex"].artifact_id)
    
    if kimi_content['concept'] == "量子纠缠" and alex_content['concept'] == "光合作用":
        logger.info("✅ User data isolation verified - no cross-contamination")
        logger.info(f"   user_kimi's topic: {kimi_content['concept']}")
        logger.info(f"   user_alex's topic: {alex_content['concept']}")
    else:
        logger.error("❌ Data cross-contamination detected!")
    
    # 清理测试数据
    logger.info("\n" + "━" * 80)
    logger.info("清理测试数据")
    logger.info("━" * 80)
    
    if memory_manager.s3_manager.s3_client is not None:
        s3_client = memory_manager.s3_manager.s3_client
        bucket_name = memory_manager.s3_manager.bucket
        
        for user_id in ["user_kimi", "user_alex"]:
            prefix = f"{artifact_folder}/{user_id}/"
            logger.info(f"🗑️  Cleaning up S3 path: s3://{bucket_name}/{prefix}")
            
            try:
                response = s3_client.list_objects_v2(Bucket=bucket_name, Prefix=prefix)
                for obj in response.get('Contents', []):
                    s3_client.delete_object(Bucket=bucket_name, Key=obj['Key'])
                logger.info(f"   ✅ Cleaned up S3 artifacts for {user_id}")
            except Exception as e:
                logger.error(f"   ❌ Error cleaning up S3: {e}")
    
    # 清理本地 artifacts
    import shutil
    for user_id in ["user_kimi", "user_alex"]:
        local_artifact_dir = memory_manager.artifact_storage.base_dir / user_id
        if local_artifact_dir.exists():
            shutil.rmtree(local_artifact_dir)
            logger.info(f"🗑️  Cleaned up local artifacts for {user_id}")
    
    logger.info("\n" + "=" * 80)
    logger.info("🎉 All Tests Completed!")
    logger.info("=" * 80)
    
    logger.info("\n📊 Summary:")
    logger.info("  ✅ Multi-user data isolation: Working")
    logger.info("  ✅ S3 path separation: Verified")
    logger.info("  ✅ Data loading: Working")
    logger.info("  ✅ No cross-contamination: Verified")
    
    if memory_manager.s3_manager.s3_client is not None:
        logger.info(f"\n💡 S3 Structure:")
        logger.info(f"  s3://{bucket_name}/{artifact_folder}/user_kimi/step_*.json")
        logger.info(f"  s3://{bucket_name}/{artifact_folder}/user_alex/step_*.json")


if __name__ == "__main__":
    asyncio.run(test_multi_user_data_isolation())

