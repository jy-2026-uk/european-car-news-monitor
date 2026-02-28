import os
import re
import json
import hashlib
import requests
import feedparser
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass, asdict
from collections import defaultdict
import time
import html

# ==================== 配置 ====================

@dataclass
class Config:
    # 飞书配置
    FEISHU_WEBHOOK = os.environ.get('FEISHU_WEBHOOK_URL')
    
    # OpenAI API (用于AI分析，可选)
    OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '')
    
    # 维度定义
    DIMENSIONS = {
        'policy': '政策监管',
        'competitor': '竞品动态', 
        'market': '市场表现',
        'brand': '品牌/舆论',
        'supply_chain': '供应链/能源'
    }
    
    # 权威源优先级 (数字越小优先级越高)
    AUTHORITY_PRIORITY = {
        'automobilwoche.de': 1,
        'kba.de': 1,
        'vda.de': 1,
        'acea.auto': 2,
        'automotive-news.eu': 2,
        'handelsblatt.com': 2,
        'manager-magazin.de': 3,
        'auto-motor-und-sport.de': 4,
        'autobild.de': 5,
        'motor1.com': 6,
        'electrive.com': 6,
    }
    
    # 监测源配置
    SOURCES = {
        # 权威源 - RSS
        'automobilwoche': 'https://www.automobilwoche.de/rss.xml',
        'acea': 'https://www.acea.auto/feed/',
        'electrive': 'https://www.electrive.com/feed/',
        
        # 德国主流媒体
        'auto_motor_sport': 'https://www.auto-motor-und-sport.de/rss/feed.xml',
        'autobild': 'https://www.autobild.de/rss/videos.xml',
        
        # 新闻搜索
        'google_policy': 'https://news.google.com/rss/search?q=EU+automotive+tariff+regulation+2024&hl=de&gl=DE&ceid=DE:de',
        'google_china_eu': 'https://news.google.com/rss/search?q=China+EV+Europe+import+tariff&hl=de&gl=DE&ceid=DE:de',
        'google_german_auto': 'https://news.google.com/rss/search?q=Deutsche+Autoindustrie+VW+BMW+Mercedes&hl=de&gl=DE&ceid=DE:de',
    }
    
    # 关键词配置
    KEYWORDS_CORE = [
        # 政策相关
        'tariff', 'zoll', 'subsid', 'subvention', 'regulation', 'verordnung',
        'anti-subsidy', 'anti-dumping', 'import duty', 'import tax',
        
        # 市场相关
        'market share', 'marktanteil', 'sales', 'verkauf', 'absatz',
        'production', 'produktion', 'factory', 'werk', 'plant closure',
        
        # 品牌相关
        'volkswagen', 'vw', 'bmw', 'mercedes', 'audi', 'porsche',
        'stellantis', 'renault', 'peugeot', 'citroen', 'volvo',
        
        # 中国出海相关
        'byd', 'nio', 'xpeng', 'geely', 'saic', 'chinese brand',
        'china import', 'chinese ev', 'chinese automaker',
        
        # 战略动态
        'layoff', 'entlassung', 'restructuring', 'restrukturierung',
        'investment', 'investition', 'joint venture', 'partnership',
    ]
    
    # 排除词
    EXCLUDE_PATTERNS = [
        r'formula\s*1', r'f1', r'racing', r'motorsport', r'grand\s*prix',
        r'crash\s*test', r'safety\s*rating', r'recall\s*specific',
        r'concept\s*car', r'auto\s*show\s*preview', r'render',
    ]

# ==================== 数据结构（更新） ====================

@dataclass
class NewsItem:
    title: str
    link: str
    summary: str
    source_name: str
    published: str
    raw_content: str = ""
    dimension: str = ""
    impact_summary: str = ""
    priority: int = 99
    hash_id: str = ""
    semantic_signature: str = ""
    
    def to_feishu_format(self, index: int) -> str:
        """转换为指定格式"""
        return f"""{index}. {self.title}
新闻摘要：{self.impact_summary}
来源网站：[{self.source_name}]({self.link})"""

# ==================== 智能去重引擎 ====================

class DeduplicationEngine:
    def __init__(self):
        self.seen_hashes = set()
        self.semantic_clusters = []
        
    def normalize_text(self, text: str) -> str:
        """文本标准化"""
        text = text.lower()
        # 移除标点、数字、停用词
        text = re.sub(r'[^\w\s]', '', text)
        text = re.sub(r'\d+', '', text)
        # 移除常见停用词
        stopwords = {'the', 'a', 'an', 'in', 'on', 'at', 'to', 'for', 'of', 'and', 'or', 'but'}
        words = [w for w in text.split() if w not in stopwords and len(w) > 2]
        return ' '.join(words)
    
    def generate_hash(self, title: str, link: str) -> str:
        """生成唯一ID"""
        content = f"{title}{link}"
        return hashlib.md5(content.encode()).hexdigest()[:16]
    
    def generate_semantic_signature(self, title: str, summary: str) -> str:
        """生成语义签名（用于相似度比较）"""
        text = self.normalize_text(title + " " + summary[:200])
        # 提取关键词组合
        keywords = []
        important_terms = [
            'tariff', 'zoll', 'vw', 'bmw', 'mercedes', 'byd', 'nio', 'china',
            'factory', 'werk', 'production', 'layoff', 'entlassung', 'joint venture'
        ]
        for term in important_terms:
            if term in text:
                keywords.append(term)
        return '|'.join(sorted(set(keywords)))
    
    def calculate_similarity(self, item1: NewsItem, item2: NewsItem) -> float:
        """计算两篇新闻的相似度 (0-1)"""
        # 标题相似度
        title_sim = self._text_similarity(item1.title, item2.title)
        # 语义签名相似度
        sig1 = set(item1.semantic_signature.split('|'))
        sig2 = set(item2.semantic_signature.split('|'))
        if not sig1 or not sig2:
            semantic_sim = 0
        else:
            intersection = len(sig1 & sig2)
            union = len(sig1 | sig2)
            semantic_sim = intersection / union if union > 0 else 0
        
        return (title_sim * 0.6) + (semantic_sim * 0.4)
    
    def _text_similarity(self, text1: str, text2: str) -> float:
        """简单文本相似度"""
        words1 = set(self.normalize_text(text1).split())
        words2 = set(self.normalize_text(text2).split())
        if not words1 or not words2:
            return 0
        intersection = len(words1 & words2)
        union = len(words1 | words2)
        return intersection / union
    
    def deduplicate(self, items: List[NewsItem]) -> List[NewsItem]:
        """去重并选择最优源"""
        # 按语义签名聚类
        clusters = defaultdict(list)
        for item in items:
            clusters[item.semantic_signature].append(item)
        
        results = []
        for sig, cluster in clusters.items():
            if len(cluster) == 1:
                results.append(cluster[0])
            else:
                # 同一事件多个来源，选择优先级最高的
                best = min(cluster, key=lambda x: (x.priority, len(x.summary)))
                results.append(best)
        
        # 二次检查：跨语义签名但内容相似的
        final_results = []
        for item in sorted(results, key=lambda x: x.priority):
            is_duplicate = False
            for existing in final_results:
                if self.calculate_similarity(item, existing) > 0.7:
                    # 保留优先级更高的
                    if item.priority < existing.priority:
                        final_results.remove(existing)
                        final_results.append(item)
                    is_duplicate = True
                    break
            if not is_duplicate:
                final_results.append(item)
        
        return sorted(final_results, key=lambda x: x.priority)

# ==================== AI分析器 ====================

class AIAnalyzer:
    def __init__(self):
        self.api_key = Config.OPENAI_API_KEY
        self.use_ai = bool(self.api_key)
        
        # 维度关键词映射（用于无AI时的备用分类）
        self.dimension_keywords = {
            'policy': ['tariff', 'zoll', 'subsid', 'regulation', 'verordnung', 'anti-dumping', 'duty', 'tax', 'eu commission', 'brussels'],
            'competitor': ['vw', 'volkswagen', 'bmw', 'mercedes', 'audi', 'porsche', 'layoff', 'entlassung', 'restructuring', 'factory closure', 'price cut'],
            'market': ['market share', 'marktanteil', 'sales figure', 'absatz', 'delivery', 'auslieferung', 'registration', 'zulassung'],
            'brand': ['byd', 'nio', 'xpeng', 'geely', 'saic', 'chinese brand', 'review', 'test', 'quality', 'recall', 'scandal'],
            'supply_chain': ['battery', 'akk', 'charging', 'ladesäule', 'infrastructure', 'raw material', 'rohstoff', 'semiconductor', 'chip']
        }
    
    def analyze(self, item: NewsItem) -> NewsItem:
        """分析新闻维度与影响"""
        if self.use_ai:
            return self._ai_analyze(item)
        else:
            return self._rule_analyze(item)
    
    def _ai_analyze(self, item: NewsItem) -> NewsItem:
        """使用OpenAI API分析"""
        try:
            prompt = f"""分析以下欧洲汽车新闻，返回JSON格式：
{{
  "dimension": "policy/competitor/market/brand/supply_chain",
  "impact_summary": "50字以内，点明核心事实及对中国品牌出海的潜在影响"
}}

标题：{item.title}
摘要：{item.summary}
来源：{item.source_name}"""

            response = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "gpt-3.5-turbo",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.3
                },
                timeout=15
            )
            
            result = response.json()
            content = result['choices'][0]['message']['content']
            # 提取JSON
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                item.dimension = data.get('dimension', 'other')
                item.impact_summary = data.get('impact_summary', item.summary[:50])
            
        except Exception as e:
            print(f"AI分析失败，使用规则分析: {e}")
            return self._rule_analyze(item)
        
        return item
    
    def _rule_analyze(self, item: NewsItem) -> NewsItem:
        """基于规则的分析（无需AI）"""
        text = (item.title + " " + item.summary).lower()
        
        # 维度分类
        scores = {}
        for dim, keywords in self.dimension_keywords.items():
            score = sum(1 for kw in keywords if kw in text)
            scores[dim] = score
        
        item.dimension = max(scores, key=scores.get) if max(scores.values()) > 0 else 'other'
        
        # 生成影响摘要（简化版）
        item.impact_summary = self._generate_impact_summary(item, text)
        
        return item
    
    def _generate_impact_summary(self, item: NewsItem, text: str) -> str:
        """生成影响摘要"""
        # 基于关键词生成模板化摘要
        if 'tariff' in text or 'zoll' in text:
            return "关税政策变化将直接影响出海成本，需评估定价策略调整。"
        elif 'layoff' in text or 'entlassung' in text:
            return "竞品人员调整可能释放市场份额，关注其产能变化。"
        elif 'byd' in text or 'nio' in text or 'xpeng' in text or 'chinese' in text:
            return "中国品牌动态值得密切关注，评估竞争策略调整。"
        elif 'factory' in text or 'werk' in text:
            return "产能布局调整可能改变区域供应格局，关注供应链机会。"
        elif 'battery' in text or 'charging' in text:
            return "基础设施与供应链变化将影响市场进入门槛。"
        else:
            # 截取前45字 + 省略号
            summary = item.summary[:45] + "..." if len(item.summary) > 45 else item.summary
            return f"{summary}（建议关注对出海策略的潜在影响）"

# ==================== 新闻获取器 ====================

class NewsFetcher:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
    
    def get_source_priority(self, url: str) -> int:
        """获取来源优先级"""
        for domain, priority in Config.AUTHORITY_PRIORITY.items():
            if domain in url.lower():
                return priority
        return 99
    
    def get_source_name(self, url: str) -> str:
        """获取来源名称"""
        domain_map = {
            'automobilwoche.de': 'Automobilwoche',
            'kba.de': 'KBA',
            'vda.de': 'VDA',
            'acea.auto': 'ACEA',
            'auto-motor-und-sport.de': 'Auto Motor und Sport',
            'autobild.de': 'Auto Bild',
            'electrive.com': 'Electrive',
            'handelsblatt.com': 'Handelsblatt',
            'manager-magazin.de': 'Manager Magazin',
        }
        for domain, name in domain_map.items():
            if domain in url.lower():
                return name
        return url.split('/')[2].replace('www.', '')
    
    def should_exclude(self, title: str, summary: str) -> bool:
        """检查是否应该排除"""
        text = (title + " " + summary).lower()
        
        # 检查排除模式
        for pattern in Config.EXCLUDE_PATTERNS:
            if re.search(pattern, text):
                return True
        
        # 检查是否与中国出海相关（如果不是，可能不重要）
        china_terms = ['china', 'chinese', 'byd', 'nio', 'xpeng', 'geely', 'saic', 'import', 'export', 'tariff', 'zoll']
        europe_terms = ['europe', 'eu', 'european', 'germany', 'german', 'deutschland']
        
        has_china = any(term in text for term in china_terms)
        has_europe = any(term in text for term in europe_terms)
        
        # 如果既不涉及中国也不涉及欧洲政策/市场，可能是普通新闻
        if not has_china and not has_europe:
            # 但如果是重大战略调整，保留
            major_terms = ['strategy', 'restructuring', 'layoff', 'factory closure', 'joint venture']
            if not any(term in text for term in major_terms):
                return True
        
        return False
    
    def fetch_rss(self, name: str, url: str) -> List[NewsItem]:
        """获取RSS源"""
        items = []
        try:
            print(f"📡 获取: {name}")
            feed = feedparser.parse(url)
            
            for entry in feed.entries[:8]:  # 每个源最多8条
                title = html.unescape(entry.get('title', ''))
                summary = html.unescape(entry.get('summary', ''))[:300]
                link = entry.get('link', '')
                published = entry.get('published', datetime.now().isoformat())
                
                # 排除检查
                if self.should_exclude(title, summary):
                    continue
                
                # 关键词检查
                text = (title + " " + summary).lower()
                if not any(kw in text for kw in Config.KEYWORDS_CORE):
                    continue
                
                item = NewsItem(
                    title=title,
                    link=link,
                    summary=summary,
                    source_name=self.get_source_name(url),
                    published=published,
                    raw_content=text,
                    priority=self.get_source_priority(url)
                )
                items.append(item)
                
        except Exception as e:
            print(f"❌ 获取失败 {name}: {e}")
        
        return items
    
    def fetch_all(self) -> List[NewsItem]:
        """获取所有源"""
        all_items = []
        
        for name, url in Config.SOURCES.items():
            items = self.fetch_rss(name, url)
            all_items.extend(items)
            time.sleep(1)  # 礼貌延迟
        
        print(f"📰 原始获取: {len(all_items)} 条")
        return all_items

# ==================== 飞书推送器（更新） ====================

class FeishuPusher:
    def __init__(self):
        self.webhook = Config.FEISHU_WEBHOOK
    
    def generate_daily_summary(self, items: List[NewsItem]) -> str:
        """生成每日一句话总结"""
        # 统计各维度数量
        dim_count = defaultdict(int)
        for item in items:
            dim_count[item.dimension] += 1
        
        # 提取关键信息生成总结
        summary_parts = []
        
        # 检查是否有重大政策
        policy_items = [i for i in items if i.dimension == 'policy']
        if policy_items:
            summary_parts.append("政策层面有新动态")
        
        # 检查中国品牌表现
        china_items = [i for i in items if any(x in i.raw_content for x in ['byd', 'nio', 'xpeng', 'chinese'])]
        if china_items:
            summary_parts.append("中国品牌动作频频")
        
        # 检查市场数据
        market_items = [i for i in items if i.dimension == 'market']
        if market_items:
            summary_parts.append("市场数据值得关注")
        
        # 检查竞品重大调整
        competitor_items = [i for i in items if i.dimension == 'competitor' and any(x in i.raw_content for x in ['layoff', 'factory', 'restructuring'])]
        if competitor_items:
            summary_parts.append("传统车企调整加速")
        
        if not summary_parts:
            return "欧洲车市动态平稳，建议持续关注政策走向与竞品策略。"
        
        return "；".join(summary_parts) + "，建议密切关注后续发展。"
    
    def send(self, items: List[NewsItem]) -> bool:
        """推送新闻列表"""
        if not items:
            print("ℹ️ 无新闻需要推送")
            return False
        
        if not self.webhook:
            print("❌ 未配置Webhook")
            return False
        
        # 生成每日总结
        daily_summary = self.generate_daily_summary(items)
        
        # 构建消息内容
        today = datetime.now().strftime("%m月%d日")
        
        content_lines = [
            f"🤖 今日({today}) 德国汽车市场新闻 🔆",
            f"✍️ 总结：{daily_summary}",
            ""
        ]
        
        # 添加新闻列表（最多8条）
        for i, item in enumerate(items[:8], 1):
            content_lines.append(item.to_feishu_format(i))
            content_lines.append("")  # 空行分隔
        
        # 添加页脚
        content_lines.append("—")
        content_lines.append("🕐 每日自动推送 | 🎯 聚焦出海战略")
        
        full_content = "\n".join(content_lines)
        
        # 构建飞书卡片
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
            response = requests.post(
                self.webhook,
                json=card,
                headers={"Content-Type": "application/json"},
                timeout=15
            )
            result = response.json()
            if result.get("code") == 0:
                print(f"✅ 推送成功: {len(items)} 条新闻")
                return True
            else:
                print(f"❌ 推送失败: {result}")
                return False
        except Exception as e:
            print(f"❌ 推送异常: {e}")
            return False

# ==================== 主控制器 ====================

class EuropeanCarMonitor:
    def __init__(self):
        self.fetcher = NewsFetcher()
        self.dedup_engine = DeduplicationEngine()
        self.analyzer = AIAnalyzer()
        self.pusher = FeishuPusher()
    
    def run(self):
        """运行完整流程"""
        print(f"\n{'='*60}")
        print(f"🚀 欧洲汽车市场新闻监控启动")
        print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*60}\n")
        
        # 1. 获取新闻
        print("📥 阶段1: 获取新闻源...")
        raw_items = self.fetcher.fetch_all()
        
        if not raw_items:
            print("⚠️ 未获取到任何新闻")
            return
        
        # 2. 生成签名和ID
        print("🔍 阶段2: 生成语义签名...")
        for item in raw_items:
            item.hash_id = self.dedup_engine.generate_hash(item.title, item.link)
            item.semantic_signature = self.dedup_engine.generate_semantic_signature(
                item.title, item.summary
            )
        
        # 3. 去重
        print("🧹 阶段3: 智能去重...")
        unique_items = self.dedup_engine.deduplicate(raw_items)
        print(f"📝 去重后: {len(unique_items)} 条")
        
        # 4. AI分析
        print("🧠 阶段4: AI分析分类...")
        analyzed_items = []
        for item in unique_items:
            analyzed_item = self.analyzer.analyze(item)
            analyzed_items.append(analyzed_item)
            time.sleep(0.5)  # 避免请求过快
        
        # 5. 按优先级和维度排序
        analyzed_items.sort(key=lambda x: (x.priority, x.dimension))
        
        # 6. 推送到飞书
        print("📤 阶段5: 推送到飞书...")
        self.pusher.send(analyzed_items)
        
        print(f"\n{'='*60}")
        print("✅ 任务完成")
        print(f"{'='*60}\n")

# ==================== 入口 ====================

if __name__ == "__main__":
    monitor = EuropeanCarMonitor()
    monitor.run()
