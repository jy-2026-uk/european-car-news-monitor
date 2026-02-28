name: European Car News Monitor

on:
  schedule:
    # 每2小时运行一次（UTC时间，北京时间+8）
    - cron: '0 */2 * * *'
  
  # 允许手动触发
  workflow_dispatch:

jobs:
  monitor:
    runs-on: ubuntu-latest
    
    steps:
    - name: Checkout code
      uses: actions/checkout@v3
    
    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: '3.10'
    
    - name: Install dependencies
      run: |
        pip install requests feedparser
    
    - name: Run monitor
      env:
        FEISHU_WEBHOOK_URL: ${{ secrets.FEISHU_WEBHOOK_URL }}
      run: python monitor.py
