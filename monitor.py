import os
import re
import json
import hashlib
import requests
import feedparser
from datetime import datetime
from typing import List, Dict
from dataclasses import dataclass
from collections import defaultdict

# ==================== 配置 ====================

@dataclass
class Config:
    FEISHU_WEBHOOK = os.environ.get('FEISHU_WEBHOOK_URL', '')
    KEYWORDS_CORE = [
        'tariff', 'zoll', 'subsid', 'regulation', 'verordnung',
        'anti-subsidy', 'anti-dumping', 'import duty',
        'volkswagen', 'vw', 'bmw', 'mercedes', 'audi', 'porsche',
        'stellantis', 'renault', 'peugeot',
        'byd', 'nio', 'xpeng', 'geely', 'saic', 'chinese brand',
        'china import', 'chinese ev', 'chinese automaker',
        'layoff', 'entlassung', 'restructuring', 'factory', 'werk',
        'market share', 'marktanteil', 'sales', 'verkauf',
        'production', 'joint venture', 'partnership',
        'battery', 'charging', 'europe', 'eu', 'german', 'deutschland'
    ]
    EXCLUDE_PATTERNS = [
        r'formula\s*1', r'f1', r'racing', r'motorsport',
        r'crash\s*test', r'safety\s*rating', r'concept\s*car',
    ]

# ==================== 日志打印 ====================

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

# ==================== 数据结构 ====================

@dataclass
class NewsItem:
    title: str
    link: str
    summary: str
    source_name: str
    published: str
    dimension: str = ""
    impact_summary: str = ""
    priority: int = 99

    def to_feishu_format(self, index: int) -> str:
        return f"""{index}. {self.title}
新闻摘要：{self.impact_summary}
来源网站：[{self.source_name}]({self.link})"""

# ==================== 新闻获取 ====================

class NewsFetcher:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        self.sources = {
            'automobilwoche': 'https://www.automobilwoche.de/rss.xml',
            'acea': 'https://www.acea.auto/feed/',
            'electrive': 'https://www.electrive.com/feed/',
            'auto_motor_sport': 'https://www.auto-motor-und-sport.de/rss/feed.xml',
            'google_german': 'https://news.google.com/rss/search?q=German+automotive+industry&hl=en&gl=DE&ceid=DE:en',
            'google_china_eu': 'https://news.google.com/rss/search?q=China+EV+Europe+tariff&hl=en&gl=DE&ceid=DE:en',
        }

    def should_exclude(self, title, summary):
        text = (title + " " + summary).lower()
        for pattern in Config.EXCLUDE_PATTERNS:
            if re.search(pattern, text):
                log(f"  ❌ 排除(匹配模式): {title[:50]}...")
                return True
        return False

    def has_keywords(self, title, summary):
        text = (title + " " + summary).lower()
        found = [kw for kw in Config.KEYWORDS_CORE if kw in text]
        if found:
            log(f"  ✅ 包含关键词: {found[:3]}")
            return True
        log(f"  ❌ 无匹配关键词: {title[:50]}...")
        return False

    def get_priority(self, url):
        if 'automobilwoche' in url:
            return 1
        elif 'acea' in url or 'vda' in url:
            return 2
        elif 'auto-motor' in url:
            return 3
        elif 'electrive' in url:
            return 4
        return 5

    def get_source_name(self, url):
        mapping = {
            'automobilwoche.de': 'Automobilwoche',
            'acea.auto': 'ACEA',
            'auto-motor-und-sport.de': 'Auto Motor und Sport',
            'electrive.com': 'Electrive',
        }
        for domain, name in mapping.items():
            if domain in url:
                return name
        return 'Google News'

    def fetch_rss(self, name, url):
        items = []
        try:
            log(f"📡 获取源: {name}")
            feed = feedparser.parse(url)
            log(f"  原始条目数: {len(feed.entries)}")
            
            for entry in feed.entries[:10]:
                title = entry.get('title', '')
                summary = entry.get('summary', '')[:300]
                link = entry.get('link', '')
                
                log(f"  检查: {title[:60]}...")
                
                # 排除检查
                if self.should_exclude(title, summary):
                    continue
                
                # 关键词检查
                if not self.has_keywords(title, summary):
                    continue
                
                item = NewsItem(
                    title=title,
                    link=link,
                    summary=summary,
                    source_name=self.get_source_name(url),
                    published=entry.get('published', ''),
                    priority=self.get_priority(url)
                )
                items.append(item)
                log(f"  ✨ 通过筛选: {title[:40]}...")
                
        except Exception as e:
            log(f"❌ 获取失败 {name}: {e}")
        
        log(f"  通过筛选: {len(items)} 条")
        return items

    def fetch_all(self):
        all_items = []
        for name, url in self.sources.items():
            items = self.fetch_rss(name, url)
            all_items.extend(items)
        log(f"\n📊 总计获取: {len(all_items)} 条")
        return all_items

# ==================== 分析器 ====================

class SimpleAnalyzer:
    def analyze(self, item):
        text = (item.title + " " + item.summary).lower()
        
        # 维度分类
        if any(x in text for x in ['tariff', 'zoll', 'duty', 'regulation', 'subsid', 'eu commission']):
            item.dimension = 'policy'
        elif any(x in text for x in ['layoff', 'entlassung', 'restructuring', 'factory', 'werk']):
            item.dimension = 'competitor'
        elif any(x in text for x in ['market share', 'marktanteil', 'sales', 'verkauf', 'delivery']):
            item.dimension = 'market'
        elif any(x in text for x in ['byd', 'nio', 'xpeng', 'geely', 'saic', 'chinese brand']):
            item.dimension = 'brand'
        else:
            item.dimension = 'other'
        
        # 生成摘要
        if 'tariff' in text or 'zoll' in text:
            item.impact_summary = "关税政策变化将直接影响出海成本，需评估定价策略调整。"
        elif 'byd' in text or 'nio' in text or 'xpeng' in text:
            item.impact_summary = "中国品牌动态值得密切关注，评估竞争策略调整。"
        elif 'layoff' in text or 'entlassung' in text:
            item.impact_summary = "竞品人员调整可能释放市场份额，关注其产能变化。"
        elif 'factory' in text or 'werk' in text:
            item.impact_summary = "产能布局调整可能改变区域供应格局，关注供应链机会。"
        else:
            item.impact_summary = item.summary[:45] + "..." if len(item.summary) > 45 else item.summary
        
        return item

# ==================== 推送器 ====================

class FeishuPusher:
    def __init__(self):
        self.webhook = Config.FEISHU_WEBHOOK
        log(f"🔧 Webhook配置: {'已设置' if self.webhook else '未设置'}")

    def generate_summary(self, items):
        if not items:
            return "今日暂无重大动态，市场平稳。"
        
        parts = []
        dims = [i.dimension for i in items]
        if 'policy' in dims:
            parts.append("政策层面有新动态")
        if 'brand' in dims:
            parts.append("中国品牌动作频频")
        if 'competitor' in dims:
            parts.append("传统车企调整加速")
        if 'market' in dims:
            parts.append("市场数据值得关注")
        
        return "；".join(parts) + "，建议密切关注后续发展。" if parts else "欧洲车市动态更新，建议关注。"

    def send(self, items):
        log(f"\n📤 准备推送: {len(items)} 条新闻")
        
        if not self.webhook:
            log("❌ 错误: Webhook未配置")
            return False
        
        if not items:
            log("ℹ️ 无新闻，发送测试消息")
            # 无新闻时也发送测试，确认通道正常
            test_msg = {
                "msg_type": "text",
                "content": {
                    "text": f"🤖 德国汽车市场日报 ({datetime.now().strftime('%m月%d日')})\n\n✍️ 总结：今日未监测到符合筛选条件的重要新闻。\n\n💡 提示：关键词可能过于严格，或新闻源暂时无更新。"
                }
            }
            try:
                resp = requests.post(self.webhook, json=test_msg, timeout=10)
                log(f"测试消息发送结果: {resp.text}")
                return resp.json().get("code") == 0
            except Exception as e:
                log(f"❌ 测试消息失败: {e}")
                return False

        # 构建正式消息
        today = datetime.now().strftime("%m月%d日")
        summary = self.generate_summary(items)
        
        content_lines = [
            f"🤖 今日({today}) 德国汽车市场新闻 🔆",
            f"✍️ 总结：{summary}",
            ""
        ]
        
        for i, item in enumerate(items[:8], 1):
            content_lines.append(item.to_feishu_format(i))
            content_lines.append("")
        
        content_lines.append("—")
        content_lines.append("🕐 每日自动推送 | 🎯 聚焦出海战略")
        
        full_content = "\n".join(content_lines)
        
        # 打印即将发送的内容（用于调试）
        log("📋 发送内容预览:")
        log("="*50)
        log(full_content[:500] + "...")
        log("="*50)
        
        card = {
            "msg_type": "interactive",
            "card": {
                "config": {"wide_screen_mode": True},
                "header": {
                    "title": {
                        "tag": "plain_text",
                        "content": f"德国汽车市场日报 {today}"
                    },
                    "template": "blue"
                },
                "elements": [
                    {
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": full_content
                        }
                    }
                ]
            }
        }
        
        try:
            log("🚀 正在发送...")
            response = requests.post(
                self.webhook,
                json=card,
                headers={"Content-Type": "application/json"},
                timeout=15
            )
            result = response.json()
            log(f"📥 飞书返回: {result}")
            
            if result.get("code") == 0:
                log("✅ 推送成功")
                return True
            else:
                log(f"❌ 推送失败: {result.get('msg')}")
                return False
        except Exception as e:
            log(f"❌ 发送异常: {e}")
            return False

# ==================== 主程序 ====================

class Monitor:
    def __init__(self):
        self.fetcher = NewsFetcher()
        self.analyzer = SimpleAnalyzer()
        self.pusher = FeishuPusher()

    def run(self):
        log("="*60)
        log("🚀 德国汽车市场新闻监控启动")
        log("="*60)
        
        # 检查配置
        if not Config.FEISHU_WEBHOOK:
            log("⚠️ 警告: FEISHU_WEBHOOK_URL 未设置")
        
        # 获取新闻
        items = self.fetcher.fetch_all()
        
        if not items:
            log("⚠️ 未获取到任何新闻，尝试发送测试消息确认通道")
            self.pusher.send([])
            return
        
        # 分析
        log(f"\n🧠 分析 {len(items)} 条新闻...")
        for item in items:
            self.analyzer.analyze(item)
            log(f"  [{item.dimension}] {item.title[:40]}...")
        
        # 去重（简单去重：相同标题）
        seen_titles = set()
        unique_items = []
        for item in items:
            title_key = item.title.lower()[:30]
            if title_key not in seen_titles:
                seen_titles.add(title_key)
                unique_items.append(item)
        
        log(f"\n📝 去重后: {len(unique_items)} 条")
        
        # 排序
        unique_items.sort(key=lambda x: x.priority)
        
        # 推送
        self.pusher.send(unique_items)
        
        log("="*60)
        log("✅ 任务完成")
        log("="*60)

if __name__ == "__main__":
    monitor = Monitor()
    monitor.run()
