import os
import sys
import configparser

# 設定你的 Key
config = configparser.ConfigParser()
config.read('config.ini')

# 設定環境變數
os.environ["GOOGLE_API_KEY"] = config.get('line-bot', 'GOOGLE_API_KEY')

print("🚀 正在載入模組，請稍候...")

try:
    # 載入必要的 RAG 工具
    from langchain_text_splitters import CharacterTextSplitter
    from langchain_community.document_loaders import TextLoader
    from langchain_community.vectorstores import Chroma
    from langchain_community.embeddings import HuggingFaceEmbeddings
    from langchain_classic.chains.retrieval_qa.base import RetrievalQA
    from langchain_google_genai import ChatGoogleGenerativeAI
except ImportError as e:
    print(f"❌ 模組載入失敗: {e}")
    sys.exit(1)

# ==========================================
# 步驟 1：準備私有資料 (秘密食譜)
# ==========================================
secret_recipe = """
【黃氏家傳特製滷肉飯食譜】
1. 豬肉選擇：必須使用「梅花肉」與「五花肉」以 3:7 的比例混合，這是口感滑順的關鍵。
2. 靈魂醬汁：燉煮時不能加水，必須全使用「可口可樂」代替水，這樣肉質會軟嫩且帶有焦糖香。
3. 秘密香料：起鍋前五分鐘，加入一小匙「即溶咖啡粉」，能提升醬汁的層次感。
4. 燉煮時間：大火煮滾後，轉微火慢燉 4 小時 20 分。
"""

# 把文字包裝成 LangChain 看得懂的 Document 格式
# 這裡我們模擬把文字切成小塊 (Chunk)，雖然這段文字很短，但這是 RAG 的標準動作
text_splitter = CharacterTextSplitter(chunk_size=500, chunk_overlap=0)
texts = text_splitter.create_documents([secret_recipe])

print(f"✅ 資料準備完成，共有 {len(texts)} 個段落。")

# ==========================================
# 步驟 2：文字向量化 & 存入資料庫
# ==========================================
print("⏳ 正在下載並初始化向量模型 (第一次會比較久)...")

# 使用免費的 HuggingFace 模型將文字轉成向量 (不用花錢呼叫 OpenAI/Google Embedding API)
embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")

# 建立暫時性的向量資料庫 (存在記憶體中，程式關掉就會消失)
db = Chroma.from_documents(texts, embeddings)

print("✅ 向量資料庫建立完成！資料已存入。")

# ==========================================
# 步驟 3：建立問答鏈 (RAG Chain)
# ==========================================
# 準備大腦 (Gemini)
llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0)

# 把資料庫變成一個「搜尋引擎 (Retriever)」
retriever = db.as_retriever(search_kwargs={"k": 1}) # k=1 代表只找最相關的那 1 段

# 建立問答鏈：它會自動做「搜尋 -> 塞入 Prompt -> 問 AI」的流程
qa = RetrievalQA.from_chain_type(llm=llm, chain_type="stuff", retriever=retriever)

# ==========================================
# 步驟 4：開始測試！
# ==========================================
query = "請問黃氏滷肉飯的秘密香料是什麼？還有要燉多久？"

print(f"\n🙋‍♂️ 你的問題：{query}")
print("🤖 AI 正在翻閱食譜並思考中...")

response = qa.invoke(query)

# 印出結果
print("\n📝 AI 的回答：")
# 處理不同版本的回傳格式 (有的版本回傳字串，有的回傳字典)
answer = response['result'] if isinstance(response, dict) else response
print(answer)