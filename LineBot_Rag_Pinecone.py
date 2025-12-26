import os
import sys
import io
import time
import json
import requests
import configparser
import hashlib
import hmac
import base64

from flask import Flask, request, abort

# LangChain & AI 相關
from langchain_core.prompts import PromptTemplate
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_classic.chains.conversational_retrieval.base import ConversationalRetrievalChain
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_pinecone import PineconeVectorStore
from pinecone import Pinecone, ServerlessSpec
import urllib.request

# 強制 UTF-8 輸出
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# ==========================================
# 1. 讀取設定檔
# ==========================================
config = configparser.ConfigParser()
config.read('config.ini')

# 設定環境變數
os.environ["GOOGLE_API_KEY"] = config.get('line-bot', 'GOOGLE_API_KEY')
os.environ["PINECONE_API_KEY"] = config.get('line-bot', 'PINECONE_API_KEY')

LINE_CHANNEL_ACCESS_TOKEN = config.get('line-bot', 'channel_access_token')
LINE_CHANNEL_SECRET = config.get('line-bot', 'channel_secret')

# ==========================================
# 2. 初始化 AI 大腦 (Pinecone RAG) - 保持不變
# ==========================================
print("🚀 正在初始化 AI 大腦 (連接 Pinecone)...")
qa_chain = None 

def init_rag_system():
    global qa_chain
    try:
        embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
        pc = Pinecone(api_key=os.environ.get("PINECONE_API_KEY"))
        index_name = "line-bot-bitcoin"

        # 檢查並建立 Index
        if index_name not in pc.list_indexes().names():
            print(f"📦 索引 {index_name} 不存在，正在建立中...")
            pc.create_index(
                name=index_name,
                dimension=384, 
                metric="cosine",
                spec=ServerlessSpec(cloud="aws", region="us-east-1")
            )
            while not pc.describe_index(index_name).status['ready']:
                time.sleep(1)

        index = pc.Index(index_name)
        
        # 檢查是否需要上傳資料
        if index.describe_index_stats()['total_vector_count'] == 0:
            print("📥 雲端資料庫為空，開始下載並處理 PDF...")
            pdf_filename = "bitcoin_paper.pdf"
            if not os.path.exists(pdf_filename):
                headers = {'User-Agent': 'Mozilla/5.0'}
                req = urllib.request.Request("https://bitcoin.org/bitcoin.pdf", headers=headers)
                with urllib.request.urlopen(req) as response, open(pdf_filename, 'wb') as out_file:
                    out_file.write(response.read())

            loader = PyPDFLoader(pdf_filename)
            docs = loader.load()
            text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
            texts = text_splitter.split_documents(docs)
            
            PineconeVectorStore.from_documents(texts, embeddings, index_name=index_name)
            print("✅ 資料上傳完畢！")
        
        vector_store = PineconeVectorStore.from_existing_index(index_name, embeddings)
        retriever = vector_store.as_retriever(search_kwargs={"k": 2})
        llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0)

        custom_template = """
        你是黃氏企業的 AI 助理。請根據下方的【參考文件】回答用戶的問題。
        如果【參考文件】中沒有答案，你可以運用你原本的知識來回答，但請說明這是你的補充知識。
        
        【參考文件】：
        {context}
        
        用戶問題：{question}
        回答：
        """
        PROMPT = PromptTemplate(template=custom_template, input_variables=["context", "question"])

        qa_chain = ConversationalRetrievalChain.from_llm(
            llm=llm,
            retriever=retriever,
            return_source_documents=True,
            combine_docs_chain_kwargs={"prompt": PROMPT}
        )
        print("✅ AI 系統準備就緒！")

    except Exception as e:
        print(f"❌ RAG 初始化失敗: {e}")

init_rag_system()

# ==========================================
# 3. 記憶體管理
# ==========================================
user_histories = {}

# ==========================================
# 4. 定義發送訊息函式 (純 Requests)
# ==========================================
def reply_to_line(reply_token, message_text):
    api_url = "https://api.line.me/v2/bot/message/reply"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"
    }
    # 建構 JSON Body
    payload = {
        "replyToken": reply_token,
        "messages": [
            {
                "type": "text",
                "text": message_text
            }
        ]
    }
    try:
        response = requests.post(api_url, headers=headers, json=payload)
        response.raise_for_status() # 如果是 4xx 或 5xx 會報錯
    except Exception as e:
        print(f"⚠️ 回覆訊息失敗: {e}, 回應內容: {response.text}")

# ==========================================
# 5. Flask Server (手動處理 Webhook)
# ==========================================
app = Flask(__name__)

@app.route("/callback", methods=['POST'])
def callback():
    # 1. 取得 Header 中的簽章
    signature = request.headers.get('X-Line-Signature', '')
    
    # 2. 取得 Body 內容 (字串格式)
    body = request.get_data(as_text=True)

    # 3. 手動驗證簽章 (安全機制)
    # 演算法：HMAC-SHA256(ChannelSecret, Body) 然後轉 Base64
    try:
        hash_val = hmac.new(
            LINE_CHANNEL_SECRET.encode('utf-8'),
            body.encode('utf-8'),
            hashlib.sha256
        ).digest()
        computed_signature = base64.b64encode(hash_val).decode('utf-8')
        
        if signature != computed_signature:
            print("❌ 簽章驗證失敗！可能是不合法的請求。")
            return 'Invalid signature', 400
    except Exception as e:
        print(f"❌ 驗證過程發生錯誤: {e}")
        return 'Error', 500

    # 4. 解析 JSON 並處理事件
    try:
        events_data = json.loads(body) # 將 JSON 字串轉為 Python Dict
        events = events_data.get('events', [])

        for event in events:
            # 只處理文字訊息事件
            if event.get('type') == 'message' and event['message'].get('type') == 'text':
                
                user_msg = event['message']['text']
                reply_token = event['replyToken']
                user_id = event['source']['userId']
                
                print(f"👤 用戶({user_id[:5]}...) 說: {user_msg}")

                # 若 AI 還沒好
                if qa_chain is None:
                    reply_to_line(reply_token, "系統啟動中，請稍後...")
                    continue

                # ---- RAG 邏輯開始 ----
                chat_history = user_histories.get(user_id, [])
                
                result = qa_chain.invoke({
                    "question": user_msg, 
                    "chat_history": chat_history
                })
                answer = result['answer']
                
                # 更新記憶
                chat_history.append((user_msg, answer))
                if len(chat_history) > 5: chat_history.pop(0)
                user_histories[user_id] = chat_history
                # ---- RAG 邏輯結束 ----

                # 發送回覆 (Call Requests)
                reply_to_line(reply_token, answer)

    except Exception as e:
        print(f"❌ 處理訊息失敗: {e}")
        return 'Error', 500
    
    return 'OK', 200

if __name__ == "__main__":
    app.run(port=5001)