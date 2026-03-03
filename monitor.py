import os
import re
import json
import requests
import feedparser
from datetime import datetime, timedelta
from typing import List, Dict
from dataclasses import dataclass
import sys

# ==================== 战略配置 ====================

@dataclass
class Config:
    FEISHU_WEBHOOK = os.environ.get('FEISHU_WEBHOOK_URL', '')
    DEEPSEEK_API_KEY = os.environ.get('DEEPSEEK_API_KEY', '')
    AI_PROVIDER = 'deepseek'
    
    # 战略关键词 (含德语核心词)
    KEYWORDS_STRATEGIC = [
        'xiaomi', 'su7', 'lei jun', 'xiaomi auto',
        'tesla', 'model 3', 'model y', 'porsche', 'taycan', 'byd', 'nio', 'xpeng', 'zeekr',
        'tariff', 'zoll', 'anti-subsidy', 'subvention', 'eu commission', 'euro ncap', 
        'homologation', 'market entry', 'germany', 'deutschland', 'beijing auto'
    ]
    
    # 噪声过滤 (排除大巴、货车、无关地区)
    EXCLUDE_PATTERNS = [
        r'bus', r'coach', r'truck', r'lorry', r'india', r'puducherry', 
        r'formula\s*1', r'racing', r'motorsport', r'bike', r'bicycle'
    ]

# ==================== 核心逻辑 ====================

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

class AIAnalyzer:
    def __init__(self):
        self.api_key = Config.DEEPSEEK_API_KEY

    def analyze_factual(self, item):
        if not self.api_key: return self._rule_fallback(item)
        
        prompt = f"""你是一位专业的全球汽车产业情报员。
请为管理层简报提供最客观、干练的新闻提炼。

新闻标题：{item['title']}
来源：{item['source']}
内容：{item['summary'][:1200]}

任务：
1. 翻译标题：必须加粗，格式为 **[英文/德文原标题]** \n **[中文翻译标题]**。
2. 新闻摘要：用两到三句话陈述核心事实，以及该动态对行业格局/政策环境的客观影响。
3. 严格准则：禁止提供任何行动建议（严禁出现“小米应该...”、“管理层需...”）。禁止带主观感情色彩。只陈述，不评价。

请以JSON格式返回：
{{
  "formatted_title": "**原标题**\\n**中文标题**",
  "news_summary": "【新闻摘要】(内容)"
}}
"""
        try:
            response = requests.post(
                "https://api.deepseek.com/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json={
                    "model": "deepseek-chat",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1
                },
                timeout=30
            )
            data = response.json()
            content = data['choices'][0]['message']['content']
            return json.loads(re.search(r'\{.*\}', content, re.DOTALL).group())
        except:
            return self._rule_fallback(item)

    def _rule_fallback(self, item):
        return {
            "formatted_title": f"**{item['title']}**",
            "news_summary": f"【新闻摘要】监测到涉及欧洲/全球市场的行业动态，源自 {item['source']}。"
        }

class StrategyMonitor:
    def __init__(self):
        self.analyzer = AIAnalyzer()
        now = datetime.utcnow() + timedelta(hours=8)
        self.end_time = now.replace(hour=9, minute=30, second=0, microsecond=0)
        self.start_time = self.end_time - timedelta(days=1)

    def fetch_news(self):
        # 扩展后的权威信源池
        sources = {
            'Handelsblatt (德报)': 'https://www.handelsblatt.com/contentexpo/feed/unternehmen',
            'Manager Magazin (德)': 'https://www.manager-magazin.de/unternehmen/index.rss',
            'Automotive News Europe': 'https://europe.autonews.com/rss/all-news', # 如果RSS失效需用Jina爬取
            'Electrive': 'https://www.electrive.com/feed/',
            'ACEA (欧汽协)': 'https://www.acea.auto/feed/',
            'Automobilwoche': 'https://www.automobilwoche.de/rss.xml'
        }
        
        valid_news = []
        for name, url in sources.items():
            log(f"正在扫描: {name}")
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries:
                    title = entry.get('title', '').lower()
                    summary = entry.get('summary', '').lower()
                    
                    # 1. 噪声过滤
                    if any(re.search(p, title + summary) for p in Config.EXCLUDE_PATTERNS):
                        continue
                    
                    # 2. 战略词匹配
                    if not any(kw in (title + summary) for kw in Config.KEYWORDS_STRATEGIC):
                        continue
                    
                    valid_news.append({
                        'title': entry.title,
                        'link': entry.link,
                        'summary': entry.summary,
                        'source': name
                    })
            except Exception as e:
                log(f"源 {name} 获取失败: {e}")
        return valid_news

    def push_to_feishu(self, results):
        if not Config.FEISHU_WEBHOOK: return
        
        today = datetime.now().strftime("%m月%d日")
        elements = [{
            "tag": "div",
            "text": {"tag": "lark_md", "content": f"📊 **小米汽车全球市场早报 | {today}**\n---\n*注：本报汇总过去24h全球权威媒体关于汽车产业、准入政策及竞品之核心动态。*"}
        }]

        # 排序：小米相关优先展示
        results.sort(key=lambda x: any(kw in x['title'].lower() for kw in ['xiaomi', 'su7']), reverse=True)

        for i, res in enumerate(results[:12]): # 增加到12条以覆盖更多信源
            analysis = self.analyzer.analyze_factual(res)
            elements.append({
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"{i+1}. {analysis['formatted_title']}\n{analysis['news_summary']}\n🔗 [阅读详情]({res['link']}) | 来源: {res['source']}\n"
                }
            })

        payload = {
            "msg_type": "interactive",
            "card": {
                "header": {"title": {"tag": "plain_text", "content": f"汽车全球市场情报简报"}, "template": "blue"},
                "elements": elements
            }
        }
        requests.post(Config.FEISHU_WEBHOOK, json=payload, timeout=15)

    def run(self):
        log("🚀 启动全球信源监控...")
        news = self.fetch_news()
        log(f"过滤后获得 {len(news)} 条高价值情报")
        self.push_to_feishu(news)
        log("✅ 简报推送完成")

if __name__ == "__main__":
    StrategyMonitor().run()
