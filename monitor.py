import requests
from bs4 import BeautifulSoup
import json
import os
from datetime import datetime

# 配置需要监控的源 (示例：以 InsideEVs 和 Auto Motor Sport 为例)
SOURCES = {
    "InsideEVs DE": "https://insideevs.de/rss/articles/all/",
    "Auto Motor und Sport": "https://www.auto-motor-und-sport.de/service/rss/news.xml",
    # 如果没有RSS，可以用直接解析HTML的方式，此处仅展示逻辑
}

class AutoMarketScraper:
    def __init__(self, history_file='history.json'):
        self.history_file = history_file
        self.history = self.load_history()

    def load_history(self):
        if os.path.exists(self.history_file):
            with open(self.history_file, 'r') as f:
                return json.load(f)
        return []

    def save_history(self, new_url):
        self.history.append(new_url)
        # 只保留最近500条记录防止文件过大
        with open(self.history_file, 'w') as f:
            json.dump(self.history[-500:], f)

    def get_dimension(self, title, content):
        """简单的关键词分类逻辑，进阶版可接入LLM API"""
        text = (title + content).lower()
        if any(k in text for k in ['zoll', 'gesetz', 'subvention', 'förderung']): return "政策监管"
        if any(k in text for k in ['vw', 'tesla', 'bmw', 'byd', 'rabatt']): return "竞品动态"
        if any(k in text for k in ['zulassung', 'absatz', 'marktanteil']): return "市场表现"
        return "品牌/其它"

    def scrape(self):
        reports = []
        for name, url in SOURCES.items():
            print(f"正在抓取: {name}...")
            try:
                # 这里使用简单的RSS解析或Request解析
                resp = requests.get(url, timeout=10)
                soup = BeautifulSoup(resp.content, 'xml') # RSS 通常是 XML 格式
                items = soup.find_all('item')[:5] # 每次取最新的5条
                
                for item in items:
                    link = item.link.text
                    title = item.title.text
                    
                    # --- 去重逻辑 ---
                    if link in self.history:
                        continue
                    
                    summary = item.description.text[:150] # 原始摘要
                    dimension = self.get_dimension(title, summary)
                    
                    # 格式化输出
                    report = f"**{len(reports)+1}. {title}**\n" \
                             f"- 摘要：{summary[:50]}...\n" \
                             f"- 维度：{dimension}\n" \
                             f"- 来源：[{name}]({link})\n"
                    
                    reports.append(report)
                    self.save_history(link)
            except Exception as e:
                print(f"抓取 {name} 出错: {e}")
        
        return "\n".join(reports)

if __name__ == "__main__":
    scraper = AutoMarketScraper()
    content = scraper.scrape()
    if content:
        print("--- 今日情报 ---")
        print(content)
        # 这里可以加入发送企业微信/钉钉/邮件的代码
    else:
        print("今日无更新")
