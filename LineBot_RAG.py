import os
import sys
import io
import json
import requests
import configparser
from flask import Flask, request, jsonify
from linebot.v3 import WebhookHandler
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage
)

# 讀取 config.ini 內的 LINE Channel、LINE Login 與自訂參數，方便集中管理密鑰。
config = configparser.ConfigParser()
config.read('config.ini')
configuration = Configuration(access_token=config.get('line-bot', 'channel_access_token'))

# 強制 UTF-8 輸出
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# ==========================================
# 🔑 設定區 (請填入你的資料)
# ==========================================
os.environ["GOOGLE_API_KEY"] = config.get('line-bot', 'GOOGLE_API_KEY')
LINE_CHANNEL_ACCESS_TOKEN = config.get('line-bot', 'channel_access_token')
handler = WebhookHandler(config.get('line-bot', 'channel_secret'))

# ==========================================
# 1. 初始化 RAG 系統 (只在啟動時跑一次)
# ==========================================
print("🚀 正在初始化 AI 大腦...")

try:
    from langchain_community.document_loaders import PyPDFLoader
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    from langchain_community.vectorstores import Chroma
    from langchain_community.embeddings import HuggingFaceEmbeddings
    from langchain_classic.chains.retrieval_qa.base import RetrievalQA
    from langchain_google_genai import ChatGoogleGenerativeAI
    import urllib.request

    # 檢查並下載 PDF (如果沒有的話)
    pdf_filename = "bitcoin_paper.pdf"
    if not os.path.exists(pdf_filename):
        print("📥 下載 PDF 中...")
        headers = {'User-Agent': 'Mozilla/5.0'}
        req = urllib.request.Request("https://bitcoin.org/bitcoin.pdf", headers=headers)
        with urllib.request.urlopen(req) as response, open(pdf_filename, 'wb') as out_file:
            out_file.write(response.read())

    # 讀取與建立索引 (這步會花一點時間)
    loader = PyPDFLoader(pdf_filename)
    docs = loader.load()
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
    texts = text_splitter.split_documents(docs)
    
    embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
    # 建立向量資料庫
    db = Chroma.from_documents(texts, embeddings)
    
    # 建立問答鏈
    llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0)
    retriever = db.as_retriever(search_kwargs={"k": 2}) # 找最相關的2段
    qa_chain = RetrievalQA.from_chain_type(llm=llm, chain_type="stuff", retriever=retriever)
    
    print("✅ AI 系統準備就緒！")

except Exception as e:
    print(f"❌ RAG 初始化失敗: {e}")
    sys.exit(1)


# ==========================================
# 2. 定義「手動回覆」函式 (取代 SDK)
# ==========================================
def reply_to_line(reply_token, message_text):
    """
    不使用 SDK，直接用 requests 發送 HTTP POST 給 LINE
    """
    api_url = "https://api.line.me/v2/bot/message/reply"
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"
    }
    
    # 建構 LINE 要求的 JSON 格式
    payload = {
        "replyToken": reply_token,
        "messages": [
            {
                "type": "text",
                "text": message_text
            }
        ]
    }
    
    # 發送請求
    response = requests.post(api_url, headers=headers, json=payload)
    
    if response.status_code == 200:
        print("✅ 訊息回覆成功")
    else:
        print(f"❌ 回覆失敗: {response.status_code}, {response.text}")


# ==========================================
# 3. Flask Server 設定
# ==========================================
app = Flask(__name__)

@app.route("/callback", methods=['POST'])
def callback():
    # 取得 LINE 傳來的原始 JSON 資料
    body = request.get_json()
    
    # 印出來看看 LINE 傳了什麼給我們 (除錯用)
    print(f"📩 收到 Webhook: {json.dumps(body, indent=2, ensure_ascii=False)}")
    
    try:
        # 解析 events (LINE 可能一次傳送多個事件)
        events = body.get('events', [])
        
        for event in events:
            # 我們只處理「文字訊息」事件
            if event.get('type') == 'message' and event['message'].get('type') == 'text':
                user_msg = event['message']['text']
                reply_token = event['replyToken']
                
                print(f"👤 用戶說: {user_msg}")
                
                # 呼叫 RAG AI 取得答案
                print("🤖 AI 思考中...")
                ai_response = qa_chain.invoke(user_msg)
                answer = ai_response['result'] if isinstance(ai_response, dict) else ai_response
                
                # 使用我們自定義的 requests 函式回傳
                reply_to_line(reply_token, answer)
                
    except Exception as e:
        print(f"❌ 處理訊息時發生錯誤: {e}")
    
    # 必須回傳 200 OK 給 LINE，不然它會以為傳送失敗
    return 'OK', 200

if __name__ == "__main__":
    # 啟動 Server 在 5001 port
    app.run(port=5001)