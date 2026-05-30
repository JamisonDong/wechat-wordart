# 📖 wechat-wordart

**微信聊天记录 → 分词统计 → SVG 词画 → 树莓派墨水屏**

将微信导出的聊天记录自动处理成可视化词画，支持部署到静态博客或通过 HTTP 接口供墨水屏定时拉取。

```
data/chat.txt
    ↓ Step 1: parser
[Message 列表]
    ↓ Step 2: segmenter (jieba)
{word: count}
    ↓ Step 3: sentiment (Ollama, 可选)
{word: count}（已过滤负面词）
    ↓ Step 4: wordlist
output/wordlist.json
    ↓ Step 5: renderer
output/wordart.svg
    ↓ Step 6: server
http://0.0.0.0:8765  ← 树莓派拉取
```

---

## 功能特性

| 功能 | 说明 |
|------|------|
| 多格式解析 | 支持 WeChat TXT / CSV 导出，自动识别多种行格式 |
| jieba 分词 | 内置中文停用词表，支持自定义词典 |
| 情感筛选 | 可选接入本地 Ollama（qwen2、phi3 等），过滤负面词汇 |
| 词表 JSON | 输出 `{word, weight, count, updated_at}` 标准格式 |
| SVG 词画 | 纯 Python 螺旋布局，零图像依赖，可嵌入 HTML |
| HTTP 接口 | 标准库实现，无 Flask/FastAPI 依赖 |
| 模块化 | 每步可单独运行，也可串联 pipeline |

---

## 快速开始

### 0. 零配置体验（仓库自带示例聊天数据）

装好依赖后，一行命令即可生成词画，无需任何配置：

```bash
pip install -r requirements.txt
python pipeline.py --input data/sample_chat.txt --output-dir output
# → output/wordlist.json + output/wordart.svg
```

用浏览器打开 `output/wordart.svg` 即可查看效果。换成你自己的聊天记录只需替换 `--input` 路径。

> 推荐使用虚拟环境（Homebrew 等"外部托管"的 Python 会拒绝全局 pip 安装）：
> ```bash
> python3 -m venv .venv && source .venv/bin/activate
> pip install -r requirements.txt
> ```

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 准备配置

```bash
cp config.example.yaml config.yaml
# 编辑 config.yaml，修改 input.path 指向你的聊天记录文件
```

### 3. 导出微信聊天记录

- **iOS**：使用 [WeChatExporter](https://github.com/BlueMatthew/WechatExporter) 导出为 txt
- **Android**：使用备份工具导出 txt/csv
- 直接在微信「聊天详情 → 聊天记录迁移与备份」导出

### 4. 运行完整流程

```bash
python pipeline.py --config config.yaml
```

输出文件：
- `output/wordlist.json` — 词表
- `output/wordart.svg` — 词画

### 5. 启动 HTTP 服务

```bash
python pipeline.py --config config.yaml --step serve
# 或直接：
python -m wechat_wordart.server --port 8765 --output-dir output
```

---

## 单步运行

每个步骤都可以独立运行：

```bash
# 仅解析 + 分词
python pipeline.py -c config.yaml --step parse segment

# 仅重新渲染（从已有 wordlist.json）
python pipeline.py -c config.yaml --step render

# 跳过情感筛选
python pipeline.py -c config.yaml --skip sentiment
```

### 命令行覆盖参数（可免改 config 直接运行）

| 参数 | 说明 |
|------|------|
| `--input, -i` | 聊天记录文件路径，覆盖 `input.path`；提供后无需 config.yaml |
| `--format, -f` | 输入格式 `txt`/`csv`，覆盖 `input.format` |
| `--output-dir, -o` | 输出目录，自动设置 wordlist.json / wordart.svg 路径 |
| `--no-sentiment` | 强制关闭情感筛选 |
| `--step, -s` | 只运行指定步骤 |
| `--skip` | 跳过指定步骤 |

## 测试

```bash
python tests/test_pipeline.py   # 纯标准库冒烟/回归测试，无需 pytest
# 或： pytest tests/
```

---

## 接入 Ollama 情感筛选

1. 安装并启动 [Ollama](https://ollama.ai)：
   ```bash
   ollama serve
   ollama pull qwen2:1.5b   # 轻量推荐
   ```

2. 在 `config.yaml` 中启用：
   ```yaml
   sentiment:
     enabled: true
     model: "qwen2:1.5b"
     base_url: "http://localhost:11434"
   ```

---

## 树莓派墨水屏接入

在树莓派上用 `cron` 定时拉取 SVG：

```bash
# crontab -e
# 每天早上 7 点刷新
0 7 * * * curl -s http://192.168.1.100:8765/wordart.svg -o /tmp/wordart.svg && /home/pi/update_eink.sh
```

`update_eink.sh` 示例（使用 `rsvg-convert` 转 PNG 后刷屏）：
```bash
#!/bin/bash
rsvg-convert -w 800 -h 600 /tmp/wordart.svg -o /tmp/wordart.png
python3 /home/pi/eink_display.py /tmp/wordart.png
```

---

## 部署到静态博客

将 `output/wordart.svg` 直接嵌入 Markdown / HTML：

```html
<img src="/assets/wordart.svg" alt="词画" style="max-width:100%">
```

或在 Hugo / Jekyll 中作为 page resource 引用。

---

## HTTP 接口文档

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | HTML 预览页 |
| GET | `/wordlist.json` | 词表 JSON |
| GET | `/wordart.svg` | SVG 词画 |
| GET | `/status` | 服务状态 JSON |
| POST | `/refresh` | 触发重新生成（需配置 callback） |

---

## 项目结构

```
wechat-wordart/
├── pipeline.py              # 主管道（各步骤串联或单独运行）
├── config.example.yaml      # 配置模板
├── requirements.txt
└── wechat_wordart/
    ├── parser/
    │   ├── base.py          # Message 数据类 + 抽象基类
    │   ├── txt_parser.py    # TXT 格式解析（多格式兼容）
    │   └── csv_parser.py    # CSV 格式解析（自动识别列名）
    ├── segmenter/
    │   ├── segmenter.py     # jieba 分词 + 词频统计
    │   └── stopwords.txt    # 中文停用词表
    ├── sentiment/
    │   └── ollama_filter.py # Ollama 情感分类（可选）
    ├── wordlist/
    │   └── generator.py     # 生成 wordlist.json
    ├── renderer/
    │   └── svg_renderer.py  # 螺旋布局 SVG 渲染（无图像依赖）
    └── server/
        └── http_server.py   # 轻量 HTTP 服务（标准库实现）
```

---

## License

MIT
