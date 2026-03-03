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
    # 飞书与AI配置
    FEISHU_WEBHOOK = os.environ.get('FEISHU_WEBHOOK_URL', '')
    DEEPSEEK_API_KEY = os.environ.get('DEEPSEEK_API_KEY', '')
    AI_PROVIDER = 'deepseek'
    
    # 核心关键词：分为三个维度，确保信息高度相关
    KEYWORDS_STRATEGIC = [
        # 1. 小米专属 (最高优先级)
        'xiaomi', 'su7', 'lei jun', 'lu weibing', 'xiaomi auto',
        # 2. 核心竞品动态
        'tesla', 'model 3', 'model y', 'porsche', 'taycan', 'byd', 'nio', 'xpeng', 'zeekr',
        # 3. 准入与壁垒 (战略关注点)
        'tariff', 'anti-subsidy', 'eu commission', 'regulation', 'euro ncap', 
        'homologation', 'charging standard', 'market entry', 'germany'
    ]
    
    # 严禁干扰：彻底剔除之前出现的“大巴”、“印度”等噪音
    EXCLUDE_PATTERNS = [
        r'bus', r'coach', r'truck', r'lorry', r'india', r'puducherry', 
        r'formula\s*1', r'racing', r'motorsport', r'crash\s*test'
    ]

# ==================== 核心逻辑 ====================

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

class AIAnalyzer:
    def __init__(self):
        self.api_key = Config.DEEPSEEK_API_KEY

    def analyze_for_management(self, item):
        if not self.api_key: return self._rule_fallback(item)
        
        # 针对小米管理层的深度Prompt
        prompt = f"""你现在是小米汽车出海战略智库的首席分析师。
请评估以下新闻对【小米汽车（Xiaomi Auto）】进入欧洲（尤其是德国）市场的战略意义。

新闻标题：{item['title']}
来源：{item['source']}
内容：{item['summary'][:1000]}

任务：
1. 翻译标题：加粗处理，格式为 **[英文原标题]** \n **[中文翻译标题]**。
2. 战略内参：提取100字以内的干货，必须包含：(1)核心事实；(2)对小米进入欧洲的直接影响；(3)给管理层的动作建议。
3. 严禁废话：不要说“这反映了...”，直接说“小米应...”或“此举将导致...”。

请以严格JSON格式返回：
{{
  "formatted_title": "**英文标题**\\n**中文标题**",
  "dimension": "policy/competitor/market/brand",
  "strategic_insight": "【战略内参】(内容)"
}}
"""
        try:
            response = requests.post(
                "https://api.deepseek.com/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json={
                    "model": "deepseek-chat",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.2
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
            "dimension": "other",
            "strategic_insight": f"【战略内参】该动态涉及欧洲市场准入/竞争，建议管理层关注其对SU7定价及当地合规性的潜在影响。"
        }

class StrategyMonitor:
    def __init__(self):
        self.analyzer = AIAnalyzer()
        # 确定时间窗口（北京时间昨天09:30 - 今天09:30）
        now = datetime.utcnow() + timedelta(hours=8)
        self.end_time = now.replace(hour=9, minute=30, second=0, microsecond=0)
        self.start_time = self.end_time - timedelta(days=1)

    def fetch_news(self):
        sources = {
            'Electrive': 'https://www.electrive.com/feed/',
            'Automobilwoche': 'https://www.automobilwoche.de/rss.xml',
            'ACEA': 'https://www.acea.auto/feed/'
        }
        
        valid_news = []
        for name, url in sources.items():
            log(f"正在扫描: {name}")
            feed = feedparser.parse(url)
            for entry in feed.entries:
                # 过滤逻辑：时间、关键词、排除项
                title = entry.get('title', '').lower()
                summary = entry.get('summary', '').lower()
                
                # 1. 排除干扰项 (排除印度、大巴等)
                if any(re.search(p, title + summary) for p in Config.EXCLUDE_PATTERNS):
                    continue
                
                # 2. 关键词匹配 (必须包含核心词)
                if not any(kw in (title + summary) for kw in Config.KEYWORDS_STRATEGIC):
                    continue
                
                valid_news.append({
                    'title': entry.title,
                    'link': entry.link,
                    'summary': entry.summary,
                    'source': name
                })
        return valid_news

    def push_to_feishu(self, results):
        if not Config.FEISHU_WEBHOOK: return
        
        today = datetime.now().strftime("%m月%d日")
        elements = [{
            "tag": "div",
            "text": {"tag": "lark_md", "content": f"🎯 **小米汽车出海战略内参 | {today}**\n*聚焦欧洲准入、竞品对标与德国市场动向*\n---"}
        }]

        for i, res in enumerate(results[:8]): # 只选最精华的8条
            analysis = self.analyzer.analyze_for_management(res)
            elements.append({
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"{i+1}. {analysis['formatted_title']}\n{analysis['strategic_insight']}\n🔗 [原文链接]({res['link']}) | 来源: {res['source']}\n"
                }
            })

        payload = {
            "msg_type": "interactive",
            "card": {
                "header": {"title": {"tag": "plain_text", "content": f"小米汽车全球市场早报"}, "template": "orange"},
                "elements": elements
            }
        }
        requests.post(Config.FEISHU_WEBHOOK, json=payload)

    def run(self):
        log("🚀 启动战略监控程序...")
        news = self.fetch_news()
        log(f"找到 {len(news)} 条战略相关新闻")
        self.push_to_feishu(news)
        log("✅ 任务完成")

if __name__ == "__main__":
    StrategyMonitor().run()
