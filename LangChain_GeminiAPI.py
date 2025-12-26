import os
# 👇 確保載入模組
from langchain_core.prompts import PromptTemplate

from langchain_core.output_parsers import CommaSeparatedListOutputParser
from langchain_google_genai import ChatGoogleGenerativeAI
import configparser

# ==========================================
# 🔑 請在下方填入你的 Google API Key
# ==========================================
# 設定你的 Key
config = configparser.ConfigParser()
config.read('config.ini')

# 設定環境變數
os.environ["GOOGLE_API_KEY"] = config.get('line-bot', 'GOOGLE_API_KEY')



# 1. 準備大腦：使用 Gemini Pro
# temperature=0.7 代表創意度，數值越高越有創意
llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0.7)

# 2. 準備整理師 (把 AI 的話轉成清單)
output_parser = CommaSeparatedListOutputParser()
format_instructions = output_parser.get_format_instructions()

# 3. 準備模具 (Prompt)
template_text = "我想要去 {地點} 旅遊 {天數} 天，請列出一份必帶的行李清單。 {format_instructions}"

travel_prompt = PromptTemplate(
    input_variables=["地點", "天數", "format_instructions"], 
    template=template_text
)

# 4. 建立鏈 (Chain)

chain = travel_prompt | llm


try:
    # 執行 Chain
    result = chain.invoke({
        "地點": "日本",
        "天數": "5",
        "format_instructions": format_instructions
    })
    
    # =========== 👇 關鍵修正區 👇 ===========
    # 我們先印出來看看 result 到底長什麼樣子
    print(f"\n🔍 原始回應類型: {type(result)}")
    # print(f"🔍 原始回應內容: {result}") 

    final_content = ""

    # 情況 A: 如果 result 是字典 (Dict)，通常內容在 'text' 裡
    if isinstance(result, dict) and 'text' in result:
        final_content = result['text']
    # 情況 B: 如果 result 是物件 (AIMessage)，內容在 .content 屬性裡 (這就是你遇到的情況)
    elif hasattr(result, 'content'):
        final_content = result.content
    # 情況 C: 它本身就是字串
    else:
        final_content = str(result)
    
    # =========== 👆 關鍵修正區 👆 ===========

    # 6. 解析 (現在 final_content 確定是純文字了)
    final_list = output_parser.parse(final_content)
    
    print("\n✅ 清單完成：")
    print(final_list)
    print(f"總共 {len(final_list)} 項物品")
    
except Exception as e:
    print(f"\n❌ 發生錯誤: {e}")