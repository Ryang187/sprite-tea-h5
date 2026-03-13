# Batch Image Generator

这个脚本使用 OpenAI 官方图片 API 批量生成图片，不是调用 `chatgpt.com` 网页接口。

## 1. 安装

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 2. 配置 API Key

```bash
export OPENAI_API_KEY="你的 OpenAI API Key"
```

## 3. 准备提示词

你可以用三种输入格式：

- `txt`：每行一个提示词
- `csv`：至少包含 `prompt` 列，可选 `filename` 列
- `jsonl`：每行一个 JSON 对象，至少包含 `prompt` 字段

示例文件：

- `prompts.txt.example`
- `prompts.csv.example`

## 4. 运行

```bash
python3 batch_generate_images.py --input prompts.txt.example --out outputs
```

如果你希望每条提示词一次生成 4 张图：

```bash
python3 batch_generate_images.py --input prompts.csv.example --out outputs --per-prompt 4
```

常用参数：

```bash
python3 batch_generate_images.py \
  --input prompts.csv.example \
  --out outputs \
  --model gpt-image-1.5 \
  --size 1024x1024 \
  --quality medium \
  --format png \
  --per-prompt 2 \
  --workers 3 \
  --retries 5 \
  --resume
```

## 自动升级后的能力

- 默认模型是 `gpt-image-1.5`
- 单次请求最多生成 10 张，所以脚本会自动把更大的数量拆分请求
- 支持 `--workers` 并发处理多条提示词
- 支持 `--retries` 自动重试失败请求
- 支持 `--resume`，已生成完成的任务会自动跳过
- 会在输出目录写入 `manifest.jsonl`，方便你后续统计成功、失败和文件路径
- 输出文件会保存到你指定的目录里

## 5. 示例

高并发批量跑：

```bash
python3 batch_generate_images.py \
  --input prompts.csv.example \
  --out outputs \
  --per-prompt 3 \
  --workers 4 \
  --retries 5 \
  --resume
```

如果上次中断了，再次执行同样命令即可续跑。
