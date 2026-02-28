import os
import re
import json
import hashlib
import requests
import feedparser
from datetime import datetime, timedelta
from typing import List, Dict
from dataclasses import dataclass
from collections import defaultdict
import sys

# ==================== 配置 ====================

@dataclass
class Config:
    FEISHU_WEBHOOK = os.environ.get('FEISHU_WEBHOOK_URL', '')
    DEEPSEEK_API_KEY = os.environ.get('DEEPSEEK_API_KEY', '')
    AI_PROVIDER = 'deepseek'
    HOURS_BACK = 24
    
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
        'battery', 'charging', 'europe', 'eu', 'german', 'deutschland', 'uk'
    ]
    EXCLUDE_PATTERNS = [
        r'formula\s*1', r'f1', r'racing', r'motorsport',
        r'crash\s*test', r'safety\s*rating', r'concept\s*car',
    ]

# ==================== 日志 ====================

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

# ==================== 数据结构 ====================

@dataclass
class NewsItem:
    title: str
    link: str
    summary: str
    source_name: str
    published: str
    pub_datetime: datetime = None
    full_content: str = ""
    dimension: str = ""
    impact_summary: str = ""
    priority: int = 99

    def to_feishu_format(self, index: int) -> str:
        return f"""{index}. {self.title}
新闻摘要：{self.impact_summary}
来源网站：[{self.source_name}]({self.link})"""

# ==================== 时间解析器 ====================

class TimeParser:
    @staticmethod
    def parse(pub_date: str) -> datetime:
        if not pub_date:
            return datetime.now()
        
        formats = [
            '%a, %d %b %Y %H:%M:%S %z',
            '%a, %d %b %Y %H:%M:%S %Z',
            '%Y-%m-%dT%H:%M:%S%z',
            '%Y-%m-%dT%H:%M:%SZ',
            '%Y-%m-%d %H:%M:%S',
            '%d %b %Y %H:%M:%S %z',
        ]
        
        for fmt in formats:
            try:
                return datetime.strptime(pub_date, fmt)
            except:
                continue
        
        return datetime.now()

# ==================== AI分析器 ====================

class AIAnalyzer:
    def __init__(self):
        self.provider = Config.AI_PROVIDER
        self.api_key = Config.DEEPSEEK_API_KEY
        
    def fetch_full_content(self, url: str) -> str:
        try:
            jina_url = f"https://r.jina.ai/http://{url.replace('https://', '').replace('http://', '')}"
            response = requests.get(jina_url, timeout=10)
            if response.status_code == 200:
                content = response.text[:1500]
                return content
        except Exception as e:
            log(f"  ⚠️ 全文获取失败: {e}")
        
        return ""
    
    def analyze_with_ai(self, item: NewsItem) -> NewsItem:
        """使用AI分析，带完整异常处理"""
        if not self.api_key:
            log("  ⚠️ 无API Key，使用规则分析")
            return self.analyze_with_rules(item)
        
        # 获取全文
        try:
            item.full_content = self.fetch_full_content(item.link)
        except Exception as e:
            log(f"  ⚠️ 获取全文异常: {e}")
            item.full_content = ""
        
        content = item.full_content if item.full_content else item.summary
        
        # 构建提示词
        prompt = f"""分析以下欧洲汽车新闻，返回JSON格式：
{{
  "dimension": "policy/competitor/market/brand/supply_chain/other",
  "impact_summary": "50字以内，点明核心事实及对中国出海的影响"
}}

标题：{item.title}
来源：{item.source_name}
内容：{content[:1000]}"""

        try:
            result = self._call_deepseek(prompt)
            log(f"  🤖 AI返回: {result[:100]}...")
            
            # 解析JSON
            json_match = re.search(r'\{.*\}', result, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                item.dimension = data.get('dimension', 'other')
                item.impact_summary = data.get('impact_summary', '')[:50]
                
                # 验证摘要有效性
                if len(item.impact_summary) < 5:
                    log(f"  ⚠️ AI摘要太短，使用规则")
                    item = self.analyze_with_rules(item)
                else:
                    log(f"  ✨ AI成功: [{item.dimension}] {item.impact_summary[:30]}...")
            else:
                log(f"  ⚠️ 未找到JSON，使用规则")
                item = self.analyze_with_rules(item)
                
        except Exception as e:
            log(f"  ⚠️ AI分析异常: {e}")
            item = self.analyze_with_rules(item)
        
        return item
    
    def _call_deepseek(self, prompt: str) -> str:
        """调用DeepSeek，带错误处理"""
        try:
            response = requests.post(
                "https://api.deepseek.com/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "deepseek-chat",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.3,
                    "max_tokens": 500
                },
                timeout=25
            )
            
            if response.status_code != 200:
                log(f"  ⚠️ API状态码: {response.status_code}")
                return "{}"
            
            result = response.json()
            if 'choices' not in result:
                log(f"  ⚠️ API返回异常: {result}")
                return "{}"
            
            return result['choices'][0]['message']['content']
            
        except Exception as e:
            log(f"  ⚠️ API调用失败: {e}")
            return "{}"
    
    def analyze_with_rules(self, item: NewsItem) -> NewsItem:
        """规则兜底，绝对安全"""
        try:
            text = (item.title + " " + item.summary).lower()
            
            china_brands = ['byd', 'nio', 'xpeng', 'geely', 'saic', 'catl', 'mg']
            has_china = any(x in text for x in china_brands)
            
            if has_china:
                item.dimension = 'brand'
            elif any(x in text for x in ['tariff', 'zoll', 'duty', 'regulation']):
                item.dimension = 'policy'
            elif any(x in text for x in ['layoff', 'entlassung', 'restructuring']):
                item.dimension = 'competitor'
            elif any(x in text for x in ['market share', 'sales', 'verkauf']):
                item.dimension = 'market'
            elif any(x in text for x in ['battery', 'charging']):
                item.dimension = 'supply_chain'
            else:
                item.dimension = 'other'
            
            # 生成摘要
            if has_china:
                item.impact_summary = "中国品牌欧洲动态，需关注产品策略与渠道扩张。"
            elif 'tariff' in text:
                item.impact_summary = "关税政策变化，需评估定价策略与本土化生产。"
            elif 'battery' in text:
                item.impact_summary = "电池供应链动态，关乎成本结构与供应安全。"
            else:
                summary = item.summary[:35] if len(item.summary) > 35 else item.summary
                summary = re.sub(r'<[^>]+>', '', summary)
                item.impact_summary = f"{summary}（建议关注出海影响）"
            
        except Exception as e:
            log(f"  ⚠️ 规则分析也失败: {e}")
            item.dimension = 'other'
            item.impact_summary = "该新闻涉及欧洲汽车市场，建议关注后续发展。"
        
        return item

# ==================== 新闻获取器 ====================

class NewsFetcher:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        self.time_parser = TimeParser()
        self.cutoff_time = datetime.now() - timedelta(hours=Config.HOURS_BACK)
        
        self.sources = {
            'automobilwoche': 'https://www.automobilwoche.de/rss.xml',
            'acea': 'https://www.acea.auto/feed/',
            'electrive': 'https://www.electrive.com/feed/',
            'auto_motor_sport': 'https://www.auto-motor-und-sport.de/rss/feed.xml',
            'google_german': 'https://news.google.com/rss/search?q=German+automotive+industry&hl=en&gl=DE&ceid=DE:en',
            'google_china_eu': 'https://news.google.com/rss/search?q=China+EV+Europe+tariff&hl=en&gl=DE&ceid=DE:en',
        }

    def is_recent(self, pub_date: str) -> bool:
        try:
            pub_dt = self.time_parser.parse(pub_date)
            if pub_dt.tzinfo:
                pub_dt = pub_dt.replace(tzinfo=None)
            return pub_dt >= self.cutoff_time
        except:
            return True  # 解析失败默认保留

    def should_exclude(self, title, summary):
        try:
            text = (title + " " + summary).lower()
            for pattern in Config.EXCLUDE_PATTERNS:
                if re.search(pattern, text):
                    return True
            return False
        except:
            return False

    def has_keywords(self, title, summary):
        try:
            text = (title + " " + summary).lower()
            return any(kw in text for kw in Config.KEYWORDS_CORE)
        except:
            return True  # 出错默认保留

    def get_priority(self, url):
        if 'automobilwoche' in url:
            return 1
        elif 'acea' in url:
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
            log(f"📡 获取: {name}")
            feed = feedparser.parse(url)
            log(f"  原始条目: {len(feed.entries)}")
            
            recent_count = 0
            for entry in feed.entries[:15]:
                try:
                    title = entry.get('title', '')
                    summary = entry.get('summary', '')[:400]
                    link = entry.get('link', '')
                    published = entry.get('published', '')
                    
                    if not self.is_recent(published):
                        continue
                    
                    recent_count += 1
                    
                    if self.should_exclude(title, summary):
                        continue
                    if not self.has_keywords(title, summary):
                        continue
                    
                    item = NewsItem(
                        title=title,
                        link=link,
                        summary=summary,
                        source_name=self.get_source_name(url),
                        published=published,
                        pub_datetime=self.time_parser.parse(published),
                        priority=self.get_priority(url)
                    )
                    items.append(item)
                    log(f"  ✨ 通过: {title[:50]}...")
                except Exception as e:
                    log(f"  ⚠️ 单条处理失败: {e}")
                    continue
            
            log(f"  24h内: {recent_count} | 通过: {len(items)}")
                
        except Exception as e:
            log(f"❌ 源失败 {name}: {e}")
        
        return items

    def fetch_all(self):
        all_items = []
        for name, url in self.sources.items():
            try:
                items = self.fetch_rss(name, url)
                all_items.extend(items)
            except Exception as e:
                log(f"❌ 源异常 {name}: {e}")
        
        try:
            all_items.sort(key=lambda x: x.pub_datetime, reverse=True)
        except:
            pass
        
        log(f"\n📊 总计(24h): {len(all_items)} 条")
        return all_items

# ==================== 推送器 ====================

class FeishuPusher:
    def __init__(self):
        self.webhook = Config.FEISHU_WEBHOOK

    def generate_summary(self, items):
        if not items:
            return "过去24小时暂无重大动态。"
        
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
            parts.append("供应链布局有新进展")
        
        return "；".join(parts) + "，建议密切关注后续发展。" if parts else "欧洲车市动态更新。"

    def send(self, items):
        if not self.webhook:
            log("❌ Webhook未配置")
            return False
        
        try:
            today = datetime.now().strftime("%m月%d日")
            summary = self.generate_summary(items)
            
            content_lines = [
                f"🤖 今日({today}) 德国汽车市场新闻 🔆",
                f"✍️ 总结：{summary}",
                ""
            ]
            
            if not items:
                content_lines.append("📭 过去24小时内未监测到符合筛选条件的重要新闻。")
                content_lines.append("")
                content_lines.append("💡 可能原因：")
                content_lines.append("• 周末/节假日新闻更新较少")
                content_lines.append("• 关键词过滤较为严格")
                content_lines.append("• RSS源暂时无更新")
            else:
                for i, item in enumerate(items[:10], 1):
                    content_lines.append(item.to_feishu_format(i))
                    content_lines.append("")
            
            content_lines.append("—")
            content_lines.append("🕐 每日9:30自动推送 | 🎯 聚焦出海战略 | 📅 覆盖前24小时")
            
            full_content = "\n".join(content_lines)
            
            log("\n📋 最终内容:")
            log("="*60)
            log(full_content[:500] + "..." if len(full_content) > 500 else full_content)
            log("="*60)
            
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
            
            response = requests.post(
                self.webhook,
                json=card,
                headers={"Content-Type": "application/json"},
                timeout=15
            )
            result = response.json()
            if result.get("code") == 0:
                log("✅ 推送成功")
                return True
            else:
                log(f"❌ 推送失败: {result}")
                return False
                
        except Exception as e:
            log(f"❌ 推送异常: {e}")
            return False

# ==================== 主程序 ====================

class Monitor:
    def __init__(self):
        self.fetcher = NewsFetcher()
        self.analyzer = AIAnalyzer()
        self.pusher = FeishuPusher()

    def run(self):
        try:
            log("="*60)
            log("🚀 德国汽车市场新闻监控")
            log(f"⏰ 时间范围: 过去{Config.HOURS_BACK}小时")
            log(f"🤖 AI: {Config.AI_PROVIDER if Config.DEEPSEEK_API_KEY else '规则模式'}")
            log("="*60)
            
            # 获取新闻
            items = self.fetcher.fetch_all()
            
            if not items:
                log("\n⚠️ 无新闻，发送空报告")
                self.pusher.send([])
                log("="*60)
                log("✅ 完成")
                log("="*60)
                return
            
            # AI分析
            log(f"\n🧠 分析 {len(items)} 条...")
            analyzed_items = []
            for i, item in enumerate(items):
                try:
                    log(f"  [{i+1}/{len(items)}] {item.title[:40]}...")
                    analyzed_item = self.analyzer.analyze_with_ai(item)
                    analyzed_items.append(analyzed_item)
                except Exception as e:
                    log(f"  ❌ 分析失败: {e}")
                    # 失败也保留，用规则兜底
                    analyzed_items.append(self.analyzer.analyze_with_rules(item))
            
            # 去重
            try:
                seen = set()
                unique_items = []
                for item in analyzed_items:
                    key = item.title.lower()[:25]
                    if key not in seen:
                        seen.add(key)
                        unique_items.append(item)
                log(f"\n📝 去重后: {len(unique_items)} 条")
            except Exception as e:
                log(f"⚠️ 去重失败，使用全部: {e}")
                unique_items = analyzed_items
            
            # 排序
            try:
                unique_items.sort(key=lambda x: (x.priority, x.pub_datetime), reverse=True)
            except:
                pass
            
            # 推送
            self.pusher.send(unique_items)
            
            log("="*60)
            log("✅ 完成")
            log("="*60)
            
        except Exception as e:
            log(f"❌❌❌ 严重错误: {e}")
            import traceback
            log(traceback.format_exc())
            sys.exit(1)

if __name__ == "__main__":
    monitor = Monitor()
    monitor.run()
