import os
import io
import sys
import urllib.request # 用來下載範例 PDF
# 強制將標準輸出 (stdout) 設定為 utf-8
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import configparser

# 設定你的 Key
config = configparser.ConfigParser()
config.read('config.ini')

# 設定環境變數
os.environ["GOOGLE_API_KEY"] = config.get('line-bot', 'GOOGLE_API_KEY')

print("🚀 正在載入模組...")

try:
    # 載入 PDF 相關工具
    from langchain_community.document_loaders import PyPDFLoader
    # 載入必要的 RAG 工具
    from langchain_text_splitters import RecursiveCharacterTextSplitter # 👈 比較高級的切塊工具
    from langchain_community.document_loaders import TextLoader
    from langchain_community.vectorstores import Chroma
    from langchain_community.embeddings import HuggingFaceEmbeddings
    from langchain_classic.chains.retrieval_qa.base import RetrievalQA
    from langchain_google_genai import ChatGoogleGenerativeAI
except ImportError as e:
    print(f"❌ 模組載入失敗: {e}")
    sys.exit(1)

# ==========================================
# 步驟 1：取得 PDF 檔案
# ==========================================
pdf_filename = "bitcoin_paper.pdf"

# 如果電腦裡沒有這個檔案，就自動從網路下載
if not os.path.exists(pdf_filename):
    print("📥 正在下載範例 PDF (比特幣白皮書)...")
    url = "https://bitcoin.org/bitcoin.pdf"
    urllib.request.urlretrieve(url, pdf_filename)
    print("✅ 下載完成！")
else:
    print("✅ 偵測到檔案已存在，直接使用。")

# ==========================================
# 步驟 2：讀取 & 切割 PDF (Chunking)
# ==========================================
print("📖 正在讀取並切割 PDF...")

# 1. 載入器
loader = PyPDFLoader(pdf_filename)
# 載入所有頁面
documents = loader.load()

# 2. 切割器 (Splitter)
# chunk_size=1000: 每塊約 1000 個字元
# chunk_overlap=200: 每塊之間重疊 200 字 (避免切斷上下文)
text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=1000, 
    chunk_overlap=200
)
# 開始切割
texts = text_splitter.split_documents(documents)

print(f"✅ 切割完成！原本 {len(documents)} 頁的 PDF，被切成了 {len(texts)} 個小段落。")
# 讓我們偷看第 1 段長什麼樣
print(f"🔍 範例段落内容: {texts[0].page_content[:100]}...")

# ==========================================
# 步驟 3：向量化 & 存入資料庫
# ==========================================
print("⏳ 正在建立向量索引 (這可能需要幾秒鐘)...")

embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
db = Chroma.from_documents(texts, embeddings)

print("✅ 資料庫準備就緒！")

# ==========================================
# 步驟 4：建立問答鏈 & 提問
# ==========================================
llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0)
retriever = db.as_retriever(search_kwargs={"k": 3}) # 改成找前 3 個相關段落
qa = RetrievalQA.from_chain_type(llm=llm, chain_type="stuff", retriever=retriever)

# --- 測試問題 ---
query = "什麼是 Proof of Work？"

print(f"\n🙋‍♂️ 你的問題：{query}")
print("🤖 AI 正在閱讀白皮書並思考中...")

try:
    response = qa.invoke(query)
    answer = response['result'] if isinstance(response, dict) else response
    print("\n📝 AI 的回答：")
    print(answer)
except Exception as e:
    print(f"❌ 發生錯誤: {e}")