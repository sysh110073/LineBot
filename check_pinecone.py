import os
import configparser
from pinecone import Pinecone

# 1. 讀取設定
config = configparser.ConfigParser()
config.read('config.ini')
api_key = config.get('line-bot', 'PINECONE_API_KEY')

# 2. 連接 Pinecone
pc = Pinecone(api_key=api_key)
index_name = "line-bot-bitcoin"
index = pc.Index(index_name)

# 3. 查看統計數據
stats = index.describe_index_stats()
print("📊 資料庫統計：")
print(f"   總筆數 (Total Vectors): {stats['total_vector_count']}")
print(f"   維度 (Dimension): {stats['dimension']}")
print("-" * 30)

# 4. 試著「搜尋」看看裡面的內容
# 因為向量資料庫不能用 "Select *", 我們用一個「全零向量」去隨便搜前 3 筆最接近的
# 384 是因為我們用 all-MiniLM-L6-v2 模型
dummy_vector = [0.1] * 384 

results = index.query(
    vector=dummy_vector,
    top_k=1,
    include_metadata=True # 重要！這樣才看得到文字
)

print("🔍 抽查前 3 筆資料內容：")
if not results['matches']:
    print("❌ 沒找到任何匹配資料，請確認資料庫是否真的有上傳成功。")
else:
    for i, match in enumerate(results['matches']):
        print(f"\n📄 第 {i+1} 筆資料 (ID: {match['id']})")
        print(f"   分數: {match['score']:.4f}")
        
        # 直接把整個 metadata 印出來看，不猜欄位名稱
        metadata = match.get('metadata', {})
        print("   📂 Metadata 內容:")
        print(metadata)
        
        # 嘗試抓取文字內容
        # LangChain 通常存在 'text' 或 'page_content'
        content = metadata.get('text') or metadata.get('page_content') or "⚠️ 找不到文字欄位"
        
        print(f"   📝 預覽文字: {content[:100]}...") # 只印前100字
        print("-" * 30)