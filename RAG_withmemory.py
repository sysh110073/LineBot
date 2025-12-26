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

from langchain_core.prompts import PromptTemplate

# 強制 UTF-8 輸出
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 讀取 config.ini 內的 LINE Channel、LINE Login 與自訂參數，方便集中管理密鑰。
config = configparser.ConfigParser()
config.read('config.ini')
configuration = Configuration(access_token=config.get('line-bot', 'channel_access_token'))
os.environ["GOOGLE_API_KEY"] = config.get('line-bot', 'GOOGLE_API_KEY')
LINE_CHANNEL_ACCESS_TOKEN = config.get('line-bot', 'channel_access_token')
handler = WebhookHandler(config.get('line-bot', 'channel_secret'))


# ==========================================
# 1. 初始化 RAG 系統
# ==========================================
print("🚀 正在初始化 AI 大腦...")

try:
    from langchain_community.document_loaders import PyPDFLoader
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    from langchain_community.vectorstores import Chroma
    from langchain_community.embeddings import HuggingFaceEmbeddings
    from langchain_classic.chains.conversational_retrieval.base import ConversationalRetrievalChain # 👈 升級：使用對話鏈
    from langchain_google_genai import ChatGoogleGenerativeAI
    import urllib.request

    # 檢查並下載 PDF
    pdf_filename = "bitcoin_paper.pdf"
    if not os.path.exists(pdf_filename):
        print("📥 下載 PDF 中...")
        headers = {'User-Agent': 'Mozilla/5.0'}
        req = urllib.request.Request("https://bitcoin.org/bitcoin.pdf", headers=headers)
        with urllib.request.urlopen(req) as response, open(pdf_filename, 'wb') as out_file:
            out_file.write(response.read())

    # 建立索引
    loader = PyPDFLoader(pdf_filename)
    docs = loader.load()
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
    texts = text_splitter.split_documents(docs)
    
    embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
    db = Chroma.from_documents(texts, embeddings)
    
    # 建立 Retriever
    retriever = db.as_retriever(search_kwargs={"k": 2})
    
    # 建立大腦
    llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0)


    # 若有文件找不到的東西，幫我根據網路上的資料去做搜尋
    custom_template = """
    你是黃氏企業的 AI 助理。請根據下方的【參考文件】回答用戶的問題。
    如果【參考文件】中沒有答案，你可以運用你原本的知識來回答，但請說明這是你的補充知識。
    
    【參考文件】：
    {context}
    
    用戶問題：{question}
    回答：
    """
    PROMPT = PromptTemplate(
        template=custom_template, 
        input_variables=["context", "question"]
    )


    # 👇 關鍵修改：建立具有「對話能力」的 Chain
    # 這個 Chain 會自動幫我們做這件事：
    # 1. 把用戶的新問題 + 歷史紀錄 -> 改寫成一個完整的問題
    # 2. 去資料庫搜尋
    # 3. 回答
    qa_chain = ConversationalRetrievalChain.from_llm(
        llm=llm,
        retriever=retriever,
        return_source_documents=True,
        combine_docs_chain_kwargs={"prompt": PROMPT}   # 👈 把我們的規則塞進去
    )
    
    print("✅ AI 系統準備就緒 (已啟用記憶功能)！")

except Exception as e:
    print(f"❌ RAG 初始化失敗: {e}")
    sys.exit(1)

# ==========================================
# 🧠 記憶體管理區
# ==========================================
# 用來儲存不同使用者的對話紀錄
# 格式: { 'user_id_1': [('問1', '答1'), ('問2', '答2')], ... }
user_histories = {}

# ==========================================
# 2. 定義「手動回覆」函式 (Requests)
# ==========================================
def reply_to_line(reply_token, message_text):
    api_url = "https://api.line.me/v2/bot/message/reply"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"
    }
    payload = {
        "replyToken": reply_token,
        "messages": [{"type": "text", "text": message_text}]
    }
    requests.post(api_url, headers=headers, json=payload)

# ==========================================
# 3. Flask Server
# ==========================================
app = Flask(__name__)

@app.route("/callback", methods=['POST'])
def callback():
    body = request.get_json()
    
    try:
        events = body.get('events', [])
        for event in events:
            if event.get('type') == 'message' and event['message'].get('type') == 'text':
                user_msg = event['message']['text']
                reply_token = event['replyToken']
                
                # 👇 取得 User ID (這是每個用戶在 LINE 裡的唯一身分證)
                user_id = event['source']['userId']
                print(f"👤 用戶({user_id[:5]}...) 說: {user_msg}")
                
                # 👇 1. 取出這位用戶的歷史紀錄 (如果沒有就給空清單)
                chat_history = user_histories.get(user_id, [])
                
                print("🤖 AI 思考中 (包含記憶)...")
                
                # 👇 2. 呼叫 AI，並把 chat_history 傳進去
                # 這裡的 invoke 參數變了，需要傳入 question 和 chat_history
                result = qa_chain.invoke({
                    "question": user_msg, 
                    "chat_history": chat_history
                })
                
                answer = result['answer']
                
                # 👇 3. 更新記憶 (把這次的問答加進去)
                # 限制記憶長度：只保留最近 5 組對話，避免 Token 爆掉
                chat_history.append((user_msg, answer))
                if len(chat_history) > 5:
                    chat_history.pop(0) # 移除最舊的一筆
                
                # 存回全域變數
                user_histories[user_id] = chat_history
                
                # 回覆用戶
                reply_to_line(reply_token, answer)
                
    except Exception as e:
        print(f"❌ 錯誤: {e}")
    
    return 'OK', 200

if __name__ == "__main__":
    app.run(port=5001)