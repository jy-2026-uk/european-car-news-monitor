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
        'byd', 'nio', 'xpeng', 'geely', 'saic', 'catl', 'mg', 'chinese brand',
        'china import', 'chinese ev', 'chinese automaker',
        'layoff', 'entlassung', 'restructuring', 'factory', 'werk',
        'market share', 'marktanteil', 'sales', 'verkauf',
        'production', 'joint venture', 'partnership',
        'battery', 'charging', 'europe', 'eu', 'german', 'deutschland', 'uk', 'united kingdom'
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
        """严格匹配用户要求的格式"""
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
                return True
        return False

    def has_keywords(self, title, summary):
        text = (title + " " + summary).lower()
        found = [kw for kw in Config.KEYWORDS_CORE if kw in text]
        return len(found) > 0

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
                log(f"  ✨ 通过: {title[:50]}...")
                
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
        
        # 检查是否涉及中国品牌（优先级最高）
        china_brands = ['byd', 'nio', 'xpeng', 'geely', 'saic', 'catl', 'mg', 'chinese brand', 'chinese ev', 'chinese automaker']
        has_china_brand = any(x in text for x in china_brands)
        
        # 维度分类
        if has_china_brand:
            item.dimension = 'brand'
        elif any(x in text for x in ['tariff', 'zoll', 'duty', 'regulation', 'verordnung', 'anti-dumping', 'eu commission', 'brussels', 'subsidy']):
            item.dimension = 'policy'
        elif any(x in text for x in ['layoff', 'entlassung', 'restructuring', 'restrukturierung', 'job cut', 'stellenabbau']):
            item.dimension = 'competitor'
        elif any(x in text for x in ['market share', 'marktanteil', 'sales figure', 'verkauf', 'absatz', 'delivery', 'zulassung', 'registration']):
            item.dimension = 'market'
        elif any(x in text for x in ['battery', 'batterie', 'charging', 'ladesäule', 'infrastructure', 'supply chain', 'lieferkette']):
            item.dimension = 'supply_chain'
        else:
            item.dimension = 'other'
        
        # 生成影响摘要
        item.impact_summary = self._generate_impact_summary(item, text, has_china_brand)
        
        return item
    
    def _generate_impact_summary(self, item, text, has_china_brand):
        """生成准确的50字以内影响摘要"""
        
        # 中国品牌相关
        if has_china_brand:
            if 'catl' in text and 'bmw' in text:
                return "宁德时代与宝马合作深化，中国供应链企业加速欧洲本土化布局。"
            elif 'battery' in text or 'batterie' in text:
                return "中国电池企业欧洲布局加速，供应链本土化趋势明显。"
            else:
                return "中国品牌欧洲市场动作频频，需关注其产品策略与渠道扩张。"
        
        # 政策相关
        if 'tariff' in text or 'zoll' in text or 'anti-dumping' in text:
            return "关税政策变化将直接影响出海成本，需评估定价策略与本土化生产。"
        if 'regulation' in text or 'verordnung' in text or 'rule' in text:
            return "欧盟监管规则调整，需评估合规成本与市场准入条件变化。"
        if 'subsidy' in text or 'subvention' in text:
            return "补贴政策变动将影响终端价格竞争力，关注政策走向。"
        
        # 竞品动态
        if 'layoff' in text or 'entlassung' in text or 'job cut' in text:
            return "传统车企人员调整，电动化转型阵痛持续，可能释放市场份额。"
        if 'factory' in text or 'werk' in text or 'plant' in text:
            if 'close' in text or 'schließung' in text:
                return "竞品产能布局调整，关注其市场空缺与供应链重构机会。"
            else:
                return "欧洲本土产能投资动态，评估供应链本地化趋势。"
        
        # 市场表现
        if 'market share' in text or 'marktanteil' in text:
            return "市场份额变化反映竞争格局调整，需关注各品牌攻防态势。"
        if 'sales' in text or 'verkauf' in text or 'absatz' in text:
            return "销量数据波动显示市场需求变化，关注消费趋势与政策影响。"
        
        # 供应链/充电
        if 'charging' in text or 'ladesäule' in text or 'infrastructure' in text:
            return "充电基础设施布局加速，影响电动车使用便利性与市场接受度。"
        if 'battery' in text or 'batterie' in text:
            return "电池技术与供应链动态，关乎成本结构与供应安全。"
        
        # 默认：基于原文生成
        summary = item.summary[:40] if len(item.summary) > 40 else item.summary
        summary = re.sub(r'<[^>]+>', '', summary)
        return f"{summary}（建议关注对出海策略的影响）"

# ==================== 推送器 ====================

class FeishuPusher:
    def __init__(self):
        self.webhook = Config.FEISHU_WEBHOOK
        log(f"🔧 Webhook: {'已配置' if self.webhook else '未配置'}")

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
        if 'supply_chain' in dims:
            parts.append("供应链布局加速")
        
        return "；".join(parts) + "，建议密切关注后续发展。" if parts else "欧洲车市动态更新，建议关注。"

    def send(self, items):
        log(f"\n📤 准备推送: {len(items)} 条")
        
        if not self.webhook:
            log("❌ Webhook未配置")
            return False
        
        today = datetime.now().strftime("%m月%d日")
        summary = self.generate_summary(items)
        
        # 构建消息内容
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
        
        # 打印预览
        log("📋 内容预览:")
        log("="*50)
        log(full_content[:300] + "...")
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
            log("🚀 发送中...")
            response = requests.post(
                self.webhook,
                json=card,
                headers={"Content-Type": "application/json"},
                timeout=15
            )
            result = response.json()
            log(f"📥 返回: {result}")
            
            if result.get("code") == 0:
                log("✅ 成功")
                return True
            else:
                log(f"❌ 失败: {result.get('msg')}")
                return False
        except Exception as e:
            log(f"❌ 异常: {e}")
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
        
        # 获取新闻
        items = self.fetcher.fetch_all()
        
        if not items:
            log("⚠️ 无新闻，发送测试消息")
            self.pusher.send([])
            return
        
        # 分析
        log(f"\n🧠 分析 {len(items)} 条...")
        for item in items:
            self.analyzer.analyze(item)
            log(f"  [{item.dimension}] {item.title[:40]}... | 摘要: {item.impact_summary[:30]}...")
        
        # 去重
        seen_titles = set()
        unique_items = []
        for item in items:
            title_key = item.title.lower()[:30]
            if title_key not in seen_titles:
                seen_titles.add(title_key)
                unique_items.append(item)
        
        log(f"\n📝 去重后: {len(unique_items)} 条")
        
        # 排序并推送
        unique_items.sort(key=lambda x: x.priority)
        self.pusher.send(unique_items)
        
        log("="*60)
        log("✅ 完成")
        log("="*60)

if __name__ == "__main__":
    monitor = Monitor()
    monitor.run()
