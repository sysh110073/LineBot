from __future__ import unicode_literals

# 載入所有 Flask、LINE Bot SDK 與系統套件，後續的 webhook、訊息處理都會依賴這些物件。
from flask import Flask, request, abort, render_template
from linebot.v3 import (
    WebhookHandler
)
from linebot.v3.exceptions import (
    InvalidSignatureError
)
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage
)
from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent
)

import requests
import json
import configparser
import os
from urllib import parse

# 建立 Flask 主體並設定靜態檔案資料夾，這樣 /static/ 下的素材才可供 LINE 使用。
app = Flask(__name__, static_url_path='/static')
UPLOAD_FOLDER = 'static'
ALLOWED_EXTENSIONS = set(['pdf', 'png', 'jpg', 'jpeg', 'gif'])


# 讀取 config.ini 內的 LINE Channel、LINE Login 與自訂參數，方便集中管理密鑰。
config = configparser.ConfigParser()
config.read('config.ini')

configuration = Configuration(access_token=config.get('line-bot', 'channel_access_token'))
handler = WebhookHandler(config.get('line-bot', 'channel_secret'))

my_line_id = config.get('line-bot', 'my_line_id')
end_point = config.get('line-bot', 'end_point')
line_login_id = config.get('line-bot', 'line_login_id')
line_login_secret = config.get('line-bot', 'line_login_secret')
my_phone = config.get('line-bot', 'my_phone')
# channel_access_token：Bot 回覆與推播都需附上的 bearer token。
# channel_secret：驗簽 signature 時使用，避免來源被偽造。
# my_line_id：pushMessage 時要送達的個人 ID。
# end_point：部屬網址，方便組合靜態檔案、LINE Login redirect URI。
# line_login_id/line_login_secret：LINE Login channel 的 client_id/client_secret。
# my_phone：按鈕選單中提供的撥號電話。
HEADER = {
    'Content-type': 'application/json',
    'Authorization': F'Bearer {config.get("line-bot", "channel_access_token")}'
}


# 建立根路由，測試 GET 時回傳 ok，若為 LINE POST 事件則解析事件內容並分流處理。
@app.route("/", methods=['POST', 'GET'])
def index():
    if request.method == 'GET':
        return 'ok'
    body = request.json
    events = body["events"]
    if request.method == 'POST' and len(events) == 0:
        return 'ok'
    print(body)
    if "replyToken" in events[0]:
        payload = dict()
        replyToken = events[0]["replyToken"]
        payload["replyToken"] = replyToken
        if events[0]["type"] == "message":
            if events[0]["message"]["type"] == "text":
                text = events[0]["message"]["text"]

                if text == "我的名字":
                    payload["messages"] = [getNameEmojiMessage()]
                elif text == "出去玩囉":
                    payload["messages"] = [getPlayStickerMessage()]
                elif text == "台北101":
                    payload["messages"] = [getTaipei101ImageMessage(),
                                           getTaipei101LocationMessage(),
                                           getMRTVideoMessage()]
                elif text == "quoda":
                    payload["messages"] = [
                            {
                                "type": "text",
                                "text": getTotalSentMessageCount()
                            }
                        ]
                elif text == "今日確診人數":
                    payload["messages"] = [
                            {
                                "type": "text",
                                "text": getTodayCovid19Message()
                            }
                        ]
                elif text == "主選單":
                    payload["messages"] = [
                            {
                                "type": "template",
                                "altText": "This is a buttons template",
                                "template": {
                                  "type": "buttons",
                                  "title": "Menu",
                                  "text": "Please select",
                                  "actions": [
                                      {
                                        "type": "message",
                                        "label": "我的名字",
                                        "text": "我的名字"
                                      },
                                      {
                                        "type": "message",
                                        "label": "今日確診人數",
                                        "text": "今日確診人數"
                                      },
                                      {
                                        "type": "uri",
                                        "label": "聯絡我",
                                        "uri": f"tel:{my_phone}"
                                      }
                                  ]
                              }
                            }
                        ]
                else:
                    payload["messages"] = [
                            {
                                "type": "text",
                                "text": text
                            }
                        ]
                replyMessage(payload)
            elif events[0]["message"]["type"] == "location":
                title = events[0]["message"]["title"]
                latitude = events[0]["message"]["latitude"]
                longitude = events[0]["message"]["longitude"]
                payload["messages"] = [getLocationConfirmMessage(title, latitude, longitude)]
                replyMessage(payload)
        elif events[0]["type"] == "postback":
            if "params" in events[0]["postback"]:
                reservedTime = events[0]["postback"]["params"]["datetime"].replace("T", " ")
                payload["messages"] = [
                        {
                            "type": "text",
                            "text": F"已完成預約於{reservedTime}的叫車服務"
                        }
                    ]
                replyMessage(payload)
            else:
                data = json.loads(events[0]["postback"]["data"])
                action = data["action"]
                if action == "get_near":
                    data["action"] = "get_detail"
                    payload["messages"] = [getCarouselMessage(data)]
                elif action == "get_detail":
                    del data["action"]
                    payload["messages"] = [getTaipei101ImageMessage(),
                                           getTaipei101LocationMessage(),
                                           getMRTVideoMessage(),
                                           getCallCarMessage(data)]
                replyMessage(payload)

    return 'OK'


# 步驟5：/callback API 走官方 SDK 驗證流程，確保 X-Line-Signature 正確後才交給 handler 處理。
@app.route("/callback", methods=['POST'])
def callback():
    # get X-Line-Signature header value
    signature = request.headers['X-Line-Signature']

    # get request body as text
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)

    # handle webhook body
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        app.logger.info("Invalid signature. Please check your channel access token/channel secret.")
        abort(400)

    return 'OK'


@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    # 此處示範「原樣回覆」的基本流程，demo 時可確認 SDK 是否可用。
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message_with_http_info(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=event.message.text)]
            )
        )



@app.route("/sendTextMessageToMe", methods=['POST'])
def sendTextMessageToMe():
    pushMessage({})
    return 'OK'


def getNameEmojiMessage():
    lookUpStr = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    productId = "5ac21a8c040ab15980c9b43f"
    name = "joe"
    message = {
        "type": "text",
        "text": "",
        "emojis": []
    }

    for char in name:
        if char in lookUpStr:
            index = lookUpStr.index(char)
            # 不夠三位數的就在前面補0
            emoji_id = f"{index + 1:03}"
            
            current_text_len = len(message["text"])
            emoji_data ={
                "index": current_text_len,
                "productId": productId,
                "emojiId": emoji_id
            }
            message["emojis"].append(emoji_data)

            message["text"] += "$"
        else:
            message["text"] += char

    # 依照 LINE Emoji 規則把輸入名字轉成對應的 emoji 表情，再組合成文字訊息。
    return message


def getCarouselMessage(data):
    message ={
        "type": "template",
        "altText": "this is a image carousel template",
        "template": {
            "type": "image_carousel",
            "columns": [
            {
                "imageUrl": F"{end_point}/static/taipei_101.jpeg",
                "action": {
                "type": "postback",
                "label": "白天101",
                "data": json.dumps(data)
                }
            },
            {
                "imageUrl": F"{end_point}/static/taipei_1.jpeg",
                "action": {
                "type": "postback",
                "label": "夜晚101",
                "data": json.dumps(data)
                }
            }
            ]
        }
    }
    # 需要使用 image carousel，使 data 內的欄位（名稱、地址、座標）渲染成多張卡片。
    return message


def getLocationConfirmMessage(title, latitude, longitude):
    message ={
    "type": "template",
    "altText": "this is a confirm template",
    "template": {
        "type": "confirm",
        "text": f"是否規劃{title}附近景點？",
        "actions": [
        {
            "type": "postback",
            "label": "是",
            "data": json.dumps({"title":title,"latitude":latitude,"longitude":longitude,"action":"get_near"}),
        },
        {
            "type": "message",
            "label": "No",
            "text": "no"
        }
        ]
    }
    }
    # 建立 Confirm 模板，讓使用者確認是否鎖定 title 所代表的地點，再利用 latitude/longitude 呼叫後續 API。
    return message


def getCallCarMessage(data):
    message ={
    "type": "template",
    "altText": "This is a buttons template",
    "template": {
        "type": "buttons",
        "text": "是否叫車？",
        "actions": [
        {
            "type": "datetimepicker",
            "label": "預約",
            "data": json.dumps(data),
            "mode": "datetime"
        },
        {
            "type": "uri",
            "label": "🚗Uber官網",
            "uri": "https://www.uber.com/tw/zh-tw/"
        }
        ]
    }
    }
    # 將 data 內的叫車資訊整理成 Bubble 或文字，提醒使用者「聯絡平台時間」。
    return message


def getPlayStickerMessage():
    message = {
    "type": "sticker",
    "packageId": "446",
    "stickerId": "1988"
    }
    # 設定 packageId、stickerId 參數即可傳貼圖，記得參考官方貼圖列表。
    return message


def getTaipei101LocationMessage():
    message = {
        "type": "location",
        "title": "my location",
        "address": "110臺北市信義區信義路五段7號",
        "latitude": 25.034067415991537,
        "longitude": 121.564524366665
    }   
    # 建立 Location Message，並填入台北 101 的 title、address、latitude、longitude。
    return message


def getMRTVideoMessage():
    message = {
    "type": "video",
    "originalContentUrl": F"{end_point}/static/mrt_sound.m4a",
    "previewImageUrl": F"{end_point}/static/taipei_101.jpeg"
    }
    # video message 需同時指定 originalContentUrl 與 previewImageUrl，可使用 static/ 目錄的素材。
    return message


def getMRTSoundMessage():
    message = dict()
    message["type"] = "audio"
    message["originalContentUrl"] = F"{end_point}/static/mrt_sound.m4a"
    import audioread
    with audioread.audio_open('static/mrt_sound.m4a') as f:
        # totalsec contains the length in float
        totalsec = f.duration
    message["duration"] = totalsec * 1000
    # 音訊訊息記得附上毫秒數 duration，否則 LINE 端會出現「音訊長度未知」而無法播放。
    return message


def getTaipei101ImageMessage(originalContentUrl=F"{end_point}/static/taipei_101.jpeg"):
    message ={
    "type": "image",
    "originalContentUrl": originalContentUrl,
    "previewImageUrl": originalContentUrl
    }
    # 此函式只是傳遞檔案位置給共用的 getImageMessage，方便之後替換不同素材。
    return getImageMessage(originalContentUrl)


def getImageMessage(originalContentUrl):
    message = {
        "type": "image",
        "originalContentUrl":originalContentUrl,
        "previewImageUrl":originalContentUrl
    }
    # image message 最少要填 originalContentUrl 與 previewImageUrl，可用同一張圖做預覽。
    return message


def replyMessage(payload):
    url = "https://api.line.me/v2/bot/message/reply"
    response = requests.post(url, headers=HEADER, json=payload)
    if response.status_code == 200:
        return "ok"
    else:
        print(response.text)
    # 使用 requests.post 呼叫 https://api.line.me/v2/bot/message/reply，
    # 直接將 payload餵入requests.post(...,json=payload)，即可在 webhook 內回覆訊息。
    return 'OK'


def pushMessage(payload):
    url = "https://api.line.me/v2/bot/message/push"
    response = requests.post(url, headers=HEADER, json=payload)
    if response.status_code == 200:
        return "ok"
    else:
        print(response.text)
    # push API 需要改打 https://api.line.me/v2/bot/message/push，
    # 並自行指定要推播的 userId（例如 my_line_id）。
    return 'OK'


def getTotalSentMessageCount():
    url = "https://api.line.me/v2/bot/message/quota/consumption"
    response = requests.get(url, headers=HEADER)
    if response.status_code == 200:
        data = response.json()
        total_usage = data.get("totalUsage", 0)
        return total_usage
    else:
        print(response.text)

    # 可呼叫 https://api.line.me/v2/bot/message/quota/consumption
    # 取得近 24 小時的回覆數量，方便統計用量。



def getTodayCovid19Message():
    response = requests.get("https://od.cdc.gov.tw/eic/NHI_COVID-19.json", verify=False)
    # 因為網址裡面儲存的格式是JSON array，要先轉編碼才能抓取回來
    response.encoding = 'utf-8-sig'
    data = response.json()[-1]
    date = f'{data["年"]}-{data["週"]}'
    count = data["健保就診總人次"]
    # 呼叫政府公開資料 API，把今日與累積確診數寫進字串後回傳。
    return F"日期：{date}, 人數：{count}"



@app.route('/line_login', methods=['GET'])
def line_login():
    # LINE Login OAuth 流程，先交換 access token，再呼叫 v2/profile 取得使用者資料。
    if request.method == 'GET':
        code = request.args.get("code", None)
        state = request.args.get("state", None)

        if code and state:
            HEADERS = {'Content-Type': 'application/x-www-form-urlencoded'}
            url = "https://api.line.me/oauth2/v2.1/token"
            FormData = {"grant_type": 'authorization_code', "code": code, "redirect_uri": F"{end_point}/line_login", "client_id": line_login_id, "client_secret":line_login_secret}
            data = parse.urlencode(FormData)
            content = requests.post(url=url, headers=HEADERS, data=data).text
            content = json.loads(content)
            url = "https://api.line.me/v2/profile"
            HEADERS = {'Authorization': content["token_type"]+" "+content["access_token"]}
            content = requests.get(url=url, headers=HEADERS).text
            content = json.loads(content)
            name = content["displayName"]
            userID = content["userId"]
            pictureURL = content["pictureUrl"]
            statusMessage = content.get("statusMessage","")
            print(content)
            return render_template('profile.html', name=name, pictureURL=
                                   pictureURL, userID=userID, statusMessage=
                                   statusMessage)
        else:
            return render_template('login.html', client_id=line_login_id,
                                   end_point=end_point)


if __name__ == "__main__":
    app.debug = True
    app.run(port=5001)
