import os
import re
import json
import requests
import feedparser
from datetime import datetime, timedelta
from typing import List, Dict
from dataclasses import dataclass
import urllib.parse

# ==================== 配置层 ====================

@dataclass
class Config:
    FEISHU_WEBHOOK = os.environ.get('FEISHU_WEBHOOK_URL', '')
    DEEPSEEK_API_KEY = os.environ.get('DEEPSEEK_API_KEY', '')
    
    # 核心战略词：涵盖中、英、德三语核心，确保精准捕获
    KEYWORDS_STRATEGIC = [
        'xiaomi', 'su7', 'lei jun', 'xiaomi auto',
        'tesla', 'model 3', 'byd', 'nio', 'xpeng', 'zeekr',
        'tariff', 'zoll', 'eu commission', 'euro ncap', 'homologation',
        'market entry', 'germany', 'deutschland', 'e-mobility', 'elektroauto'
    ]
    
    # 噪声过滤：排除非乘用车及无关地区
    EXCLUDE_PATTERNS = [
        r'bus', r'coach', r'truck', r'lorry', r'india', r'formula\s*1', 
        r'racing', r'motorsport', r'bicycle', r'ebike', r'scooter'
    ]

# ==================== 逻辑处理 ====================

class AIAnalyzer:
    def __init__(self):
        self.api_key = Config.DEEPSEEK_API_KEY

    def analyze_factual(self, item):
        if not self.api_key: return self._rule_fallback(item)
        
        # 强制“情报员”视角，严禁主观建议
        prompt = f"""你是一位专业的全球汽车产业情报员。请为小米汽车管理层提供客观的新闻摘要。
新闻标题：{item['title']}
来源：{item['source']}
内容：{item['summary'][:1200]}

任务：
1. 翻译标题：必须加粗，格式为 **[原标题]** \n **[中文标题]**。
2. 新闻摘要：用两到三句话陈述：(1)核心事实；(2)该动态对行业环境或竞争格局的客观影响。
3. 严格禁令：严禁提供任何行动建议（禁止使用“小米应该...”、“建议关注...”）。只陈述事实，不评价。

请以JSON格式返回：
{{
  "formatted_title": "**Title**\\n**标题**",
  "news_summary": "【新闻摘要】(内容)"
}}"""
        try:
            response = requests.post(
                "https://api.deepseek.com/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json={"model": "deepseek-chat", "messages": [{"role": "user", "content": prompt}], "temperature": 0.1},
                timeout=30
            )
            return json.loads(re.search(r'\{.*\}', response.json()['choices'][0]['message']['content'], re.DOTALL).group())
        except:
            return self._rule_fallback(item)

    def _rule_fallback(self, item):
        return {"formatted_title": f"**{item['title']}**", "news_summary": "【新闻摘要】监测到涉及欧洲市场的行业动态。"}

class IntelligenceMonitor:
    def __init__(self):
        self.analyzer = AIAnalyzer()

    def fetch_all(self):
        all_items = []
        
        # 精选的德国/欧洲权威 RSS 信源池
        rss_sources = {
            'Automotive News Europe': 'https://europe.autonews.com/rss/all-news', # 全球行业标杆
            'Electrive': 'https://www.electrive.com/feed/', # 电动车垂直最快
            'Heise Autos (德)': 'https://www.heise.de/autos/rss/automobil-aktuell.rdf', # 德国科技视角
            'Transport & Environment': 'https://www.transportenvironment.org/feed/', # 欧盟政策风向标
            'ACEA (欧汽协)': 'https://www.acea.auto/feed/', # 官方统计与政策游说
            'Focus Online Auto (德)': 'http://rss.focus.de/auto/', # 德国主流舆论
            'Automobilwoche (德)': 'https://www.automobilwoche.de/rss.xml' # 德国行业周刊
        }
        
        for name, url in rss_sources.items():
            print(f"📡 正在拉取: {name}...")
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries:
                    all_items.append({
                        'title': entry.title,
                        'link': entry.link,
                        'summary': entry.get('summary', ''),
                        'source': name
                    })
            except Exception as e:
                print(f"⚠️ {name} 连接失败: {e}")

        # 增加 Google News 补盲（路透、彭博等无法直接 RSS 的源）
        queries = ['"Xiaomi Auto" Europe', 'EU electric car tariff China', 'German EV market competition']
        for q in queries:
            url = f"https://news.google.com/rss/search?q={urllib.parse.quote(q)}+when:24h&hl=en-US&gl=US&ceid=US:en"
            feed = feedparser.parse(url)
            for entry in feed.entries[:8]:
                all_items.append({'title': entry.title, 'link': entry.link, 'summary': '', 'source': 'Global Intelligence'})

        # 去重与关键词过滤
        final_list = []
        seen_links = set()
        for item in all_items:
            if item['link'] in seen_links: continue
            text = (item['title'] + item['summary']).lower()
            if any(re.search(p, text) for p in Config.EXCLUDE_PATTERNS): continue
            if not any(kw in text for kw in Config.KEYWORDS_STRATEGIC): continue
            
            seen_links.add(item['link'])
            final_list.append(item)
            
        return final_list

    def push(self, items):
        if not Config.FEISHU_WEBHOOK or not items: return
        
        # 权重排序：小米/SU7 关键词绝对优先
        items.sort(key=lambda x: any(kw in x['title'].lower() for kw in ['xiaomi', 'su7']), reverse=True)
        
        today = datetime.now().strftime("%Y年%m月%d日")
        elements = [{"tag": "div", "text": {"tag": "lark_md", "content": f"🌍 **小米汽车全球情报日报 | {today}**\n---\n*汇聚欧洲主流行业信源与官方智库动态。*"}}]
        
        for i, item in enumerate(items[:15]):
            res = self.analyzer.analyze_factual(item)
            elements.append({
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"{i+1}. {res['formatted_title']}\n{res['news_summary']}\n🔗 [查看原文]({item['link']}) | 来源: {item['source']}\n"
                }
            })

        payload = {"msg_type": "interactive", "card": {"header": {"title": {"tag": "plain_text", "content": "全球汽车市场情报汇总"}, "template": "blue"}, "elements": elements}}
        requests.post(Config.FEISHU_WEBHOOK, json=payload, timeout=15)

if __name__ == "__main__":
    monitor = IntelligenceMonitor()
    news = monitor.fetch_all()
    print(f"✅ 成功提取 {len(news)} 条情报")
    monitor.push(news)
