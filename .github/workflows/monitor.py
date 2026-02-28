import requests
import feedparser
import json
import hashlib
import os
from datetime import datetime

# 从环境变量读取配置
FEISHU_WEBHOOK_URL = os.environ.get('FEISHU_WEBHOOK_URL')
KEYWORDS = [
    "European car", "EU automotive", "Volkswagen", "BMW", "Mercedes", 
    "Audi", "Porsche", "Volvo", "Peugeot", "Renault", "Ferrari", 
    "Lamborghini", "Stellantis", "EU auto industry", "European EV",
    "electric vehicle Europe", "EU car market", "European automobile"
]

RSS_FEEDS = [
    "https://www.autonews.com/rss.xml",
    "https://www.euronews.com/tag/automobile/rss",
    "https://www.autocar.co.uk/rss",
    "https://www.electrive.com/feed/",
]

GOOGLE_NEWS_URLS = [
    "https://news.google.com/rss/search?q=European+car+industry&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=Volkswagen+BMW+Mercedes&hl=en-US&gl=US&ceid=US:en",
]

class NewsMonitor:
    def __init__(self):
        self.history = set()
    
    def check_keywords(self, text):
        text = text.lower()
        return any(keyword.lower() in text for keyword in KEYWORDS)
    
    def fetch_rss(self, url):
        try:
            feed = feedparser.parse(url)
            news_list = []
            for entry in feed.entries[:5]:
                news_list.append({
                    "title": entry.get("title", ""),
                    "link": entry.get("link", ""),
                    "summary": entry.get("summary", "")[:100] + "...",
                    "source": feed.feed.get("title", "未知来源")
                })
            return news_list
        except Exception as e:
            print(f"RSS错误: {e}")
            return []
    
    def send_to_feishu(self, news):
        try:
            card = {
                "msg_type": "interactive",
                "card": {
                    "config": {"wide_screen_mode": True},
                    "header": {
                        "title": {"tag": "plain_text", "content": "🚗 欧洲汽车新闻"},
                        "template": "blue"
                    },
                    "elements": [
                        {
                            "tag": "div",
                            "text": {"tag": "lark_md", "content": f"**{news['title']}**"}
                        },
                        {
                            "tag": "div",
                            "text": {"tag": "lark_md", "content": news['summary']}
                        },
                        {
                            "tag": "div",
                            "text": {"tag": "lark_md", "content": f"📰 {news['source']} | {datetime.now().strftime('%m-%d %H:%M')}"}
                        },
                        {
                            "tag": "action",
                            "actions": [{
                                "tag": "button",
                                "text": {"tag": "plain_text", "content": "阅读全文"},
                                "type": "primary",
                                "url": news['link']
                            }]
                        }
                    ]
                }
            }
            
            response = requests.post(
                FEISHU_WEBHOOK_URL,
                json=card,
                headers={"Content-Type": "application/json"},
                timeout=10
            )
            return response.json().get("code") == 0
        except Exception as e:
            print(f"发送错误: {e}")
            return False
    
    def run(self):
        print(f"🔍 开始监控 - {datetime.now()}")
        
        all_news = []
        
        # 获取RSS
        for url in RSS_FEEDS:
            all_news.extend(self.fetch_rss(url))
        
        # 获取Google News
        for url in GOOGLE_NEWS_URLS:
            try:
                import time
                time.sleep(1)
                response = requests.get(url, timeout=10)
                feed = feedparser.parse(response.content)
                for entry in feed.entries[:3]:
                    all_news.append({
                        "title": entry.get("title", ""),
                        "link": entry.get("link", ""),
                        "summary": entry.get("summary", "")[:100] + "...",
                        "source": "Google News"
                    })
            except Exception as e:
                print(f"Google News错误: {e}")
        
        print(f"📰 获取 {len(all_news)} 条新闻")
        
        sent = 0
        for news in all_news:
            if self.check_keywords(news['title'] + " " + news['summary']):
                if self.send_to_feishu(news):
                    sent += 1
                    import time
                    time.sleep(1)
        
        print(f"✅ 发送 {sent} 条新闻")

if __name__ == "__main__":
    if not FEISHU_WEBHOOK_URL:
        print("❌ 错误：未设置 FEISHU_WEBHOOK_URL")
        exit(1)
    
    monitor = NewsMonitor()
    monitor.run()
