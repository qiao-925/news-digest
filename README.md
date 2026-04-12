# 📰 News Digest

每日新闻聚合简报，自动从 50+ 中英文信息源拉取、聚类、排序，生成一页式阅读页面。

## 在线阅读

**👉 [https://qiao-925.github.io/news-digest/](https://qiao-925.github.io/news-digest/)**

每天北京时间 07:00 自动更新。

## 信息源

| 类型 | 来源 |
|------|------|
| 科技中文 | 少数派、36氪、钛媒体、IT之家、爱范儿、虎嗅 |
| 科技英文 | Hacker News、TechCrunch、The Verge、Wired、Ars Technica |
| 开发者 | 掘金、V2EX、GitHub Trending、Product Hunt |
| 学术/AI | arXiv (多子领域)、HF Papers、The Batch、Epoch AI |
| 国际时事 | 联合早报、经济学人、华尔街日报 |
| 生活/文化 | 新周刊、三联生活、知乎热榜、读库 |
| 独立博客 | 阮一峰、酷壳、云风、月光博客 等 |

## 核心机制

- **语义聚类** — 使用 `sentence-transformers` (paraphrase-multilingual-MiniLM) 将标题转为向量，余弦相似度 ≥ 0.6 的文章自动合并
- **对数评分** — `log(源数量 + 1)`，多源报道的新闻排在前面
- **分类降噪** — 每个分类首屏 7 条，展开可看更多，避免信息过载

## 技术栈

- Python 单文件脚本
- sentence-transformers + jieba
- GitHub Actions 定时运行
- GitHub Pages 静态托管

## 本地运行

```bash
pip install -r requirements.txt
python news_digest.py --force
```

生成文件在 `docs/` 目录下。
