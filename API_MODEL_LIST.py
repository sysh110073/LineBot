import os
import google.generativeai as genai
import configparser

# 設定你的 Key
config = configparser.ConfigParser()
config.read('config.ini')

# 設定環境變數
os.environ["GOOGLE_API_KEY"] = config.get('line-bot', 'GOOGLE_API_KEY')
genai.configure(api_key=os.environ["GOOGLE_API_KEY"])

print("🔍 你的 API Key 可以使用的模型列表：")
try:
    for m in genai.list_models():
        if 'generateContent' in m.supported_generation_methods:
            print(f"- {m.name}")
except Exception as e:
    print(f"查詢失敗: {e}")