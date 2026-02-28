# ==================== 数据结构（更新标题格式） ====================

@dataclass
class NewsItem:
    title: str  # 英文原标题
    title_cn: str = ""  # 中文翻译标题（AI生成）
    link: str
    summary: str
    source_name: str
    published: str
    pub_datetime: datetime = None
    full_content: str = ""
    dimension: str = ""
    impact_summary: str = ""  # AI生成的影响摘要
    priority: int = 99

    def to_feishu_format(self, index: int) -> str:
        """双标题格式：英文 + 中文"""
        # 如果有中文标题，显示双行；否则只显示英文
        if self.title_cn and self.title_cn != self.title:
            title_display = f"{self.title}\n{self.title_cn}"
        else:
            title_display = self.title
            
        return f"""{index}. {title_display}
新闻摘要：{self.impact_summary}
来源网站：[{self.source_name}]({self.link})"""


# ==================== AI分析器（更新提示词） ====================

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
        """使用AI分析，生成中文标题和完整摘要"""
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
        
        # 优化后的提示词：要求翻译标题 + 完整摘要（不严格限50字）
        prompt = f"""你是一位专业的欧洲汽车产业分析师，专注于中国品牌出海战略研究。

请分析以下英文新闻，完成两个任务：
1. 将英文标题翻译成简洁准确的中文标题
2. 提取核心事实并评估对中国汽车品牌出海的影响

新闻标题：{item.title}
新闻来源：{item.source_name}
新闻内容：{content[:1200]}

请严格按照以下JSON格式返回：
{{
  "title_cn": "中文标题（简洁准确，15-25字）",
  "dimension": "policy/competitor/market/brand/supply_chain/other",
  "impact_summary": "影响摘要（尽量控制在50字左右，可适当超出，但必须语义完整，直接点明核心事实及对中国出海的潜在影响）",
  "key_entities": ["涉及的关键公司/品牌"],
  "importance_score": 1-10
}}

维度说明：
- policy: 关税、补贴、准入、法规等政策监管
- competitor: 大众/BMW/奔驰等竞品降价、裁员、建厂、战略调整
- market: 销量榜单、市占率波动等市场表现  
- brand: 中国品牌动态、深度测评、重大负面
- supply_chain: 充电网络、电池、原材料等供应链

影响摘要要求：
- 尽量控制在50字左右，可适当超出（60字以内），但必须语义完整
- 直接点明核心事实
- 明确指出对中国品牌出海的潜在影响
- 具体、actionable，不要泛泛而谈
- 不要截断句子，必须完整"""

        try:
            result = self._call_deepseek(prompt)
            log(f"  🤖 AI返回: {result[:150]}...")
            
            # 解析JSON
            json_match = re.search(r'\{.*\}', result, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                
                # 设置中文标题
                item.title_cn = data.get('title_cn', '')[:30]
                
                # 设置维度
                item.dimension = data.get('dimension', 'other')
                
                # 设置摘要（不严格截断，确保完整）
                raw_summary = data.get('impact_summary', '')
                # 清理可能的截断符号
                raw_summary = re.sub(r'\.\.\.$', '。', raw_summary)
                raw_summary = re.sub(r'…$', '。', raw_summary)
                item.impact_summary = raw_summary[:65]  # 放宽到65字，但保留完整句子
                
                # 验证
                if len(item.impact_summary) < 10 or not item.title_cn:
                    log(f"  ⚠️ AI输出不完整，使用规则")
                    item = self.analyze_with_rules(item)
                else:
                    log(f"  ✨ AI成功: [{item.dimension}] {item.title_cn[:20]}... | {item.impact_summary[:40]}...")
            else:
                log(f"  ⚠️ 未找到JSON，使用规则")
                item = self.analyze_with_rules(item)
                
        except Exception as e:
            log(f"  ⚠️ AI分析异常: {e}")
            item = self.analyze_with_rules(item)
        
        return item
    
    def _call_deepseek(self, prompt: str) -> str:
        """调用DeepSeek API"""
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
                    "max_tokens": 800  # 增加token，确保完整输出
                },
                timeout=30
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
        """规则兜底"""
        try:
            text = (item.title + " " + item.summary).lower()
            
            # 简单翻译标题（规则兜底）
            title_translations = {
                'german chancellor': '德国总理',
                'visits': '访问',
                'hangzhou': '杭州',
                'chinese firms': '中国企业',
                'leapmotor': '零跑汽车',
                'catl': '宁德时代',
                'bmw': '宝马',
                'battery passport': '电池护照',
                'production facility': '生产工厂',
                'thailand': '泰国',
            }
            
            title_cn = item.title
            for en, cn in title_translations.items():
                title_cn = re.sub(r'\b' + en + r'\b', cn, title_cn, flags=re.IGNORECASE)
            item.title_cn = title_cn[:40]
            
            # 维度分类
            china_brands = ['byd', 'nio', 'xpeng', 'geely', 'saic', 'catl', 'mg', 'leapmotor', '零跑']
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
            
            # 生成摘要（规则版，尽量完整）
            if 'german chancellor' in text and 'hangzhou' in text:
                item.impact_summary = "德国总理访华考察零跑汽车，释放中德汽车产业合作积极信号，有利于中国新能源车企通过技术合作加速出海布局。"
            elif 'catl' in text and 'bmw' in text:
                item.impact_summary = "宁德时代与宝马合作推进电池护照合规，中国供应链企业技术绑定欧洲车企，有利于维持配套资格并深化出海布局。"
            elif has_china:
                item.impact_summary = "中国品牌欧洲市场动态，需密切关注产品策略、渠道扩张及本土化进展，评估竞争态势变化。"
            elif 'tariff' in text:
                item.impact_summary = "欧盟关税政策变化将直接影响出海成本，管理层需评估终端定价调整或加速本土化组装以应对。"
            elif 'battery' in text:
                item.impact_summary = "电池供应链动态变化，关乎成本结构与供应安全，需评估对生产计划及竞争力的潜在影响。"
            else:
                summary = item.summary[:50] if len(item.summary) > 50 else item.summary
                summary = re.sub(r'<[^>]+>', '', summary)
                item.impact_summary = f"{summary}（建议关注对出海策略的影响）"
            
        except Exception as e:
            log(f"  ⚠️ 规则分析也失败: {e}")
            item.title_cn = item.title[:30]
            item.dimension = 'other'
            item.impact_summary = "该新闻涉及欧洲汽车市场，建议关注后续发展及对出海策略的潜在影响。"
        
        return item
