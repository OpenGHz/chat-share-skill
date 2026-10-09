<div align="center">

# chat-share

**把 AI 对话分享链接整理成核对过的文档。可以交给编码 agent，也可以直接在终端里用。**

[English](README.md) | 简体中文

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Agent skill](https://img.shields.io/badge/agent-skill-6E56CF.svg)](#安装)
[![stdlib only](https://img.shields.io/badge/python-stdlib--only-lightgrey.svg)](scripts/fetch_share.py)

</div>

贴入 `chat.deepseek.com/share/...` 或 `kimi.com/share/...` 链接，就能拿到完整对话，其中每条引用都解析成模型实际读过的页面。之后 skill 会先对照原始来源逐条核对，核对完才写文档。

仓库分两部分，可以单独使用：

- **`scripts/fetch_share.py`**：普通的 Python 命令行工具，只用标准库，不需要浏览器、cookie 或账号。
- **`SKILL.md`**：整理流程。先抓取对话，列出其中可核对的论断，逐条对照原始来源核对；文档只写核对通过的内容，其余错误单独列成更正表。

## 为什么需要它

分享页面和其中的回答，都不能直接拿来用：

- **分享页面是空壳。** 直接抓取只能得到 `<div id="app"></div>`。对话内容来自未公开的内部接口：DeepSeek 是 REST 接口，Kimi 是 Connect RPC。部分 Kimi 分享不带访客 token 时，会一律返回“分享不存在”。
- **Kimi 的引用只是编号，不是链接。** 回答里的引用写成 `tools://web_search:3#16`，指的是该次工具调用返回的第几个结果。这个编号从 0 开始，结果 id 却从 1 开始。脚本会把每条引用解析成真实 URL，并保留模型引用的原句和 Kimi 缓存的页面副本。OpenReview 的 PDF 常返回 403，这时缓存副本往往是唯一能读到的版本。
- **回答会偏离来源。** 用两个真实分享对照论文核对，发现了这些错误：图中数值是编造的；表格读错了列；两个消融变体说反了；只在真机任务上得到的数字被当成整体结果；只在玩具实验里观察到的现象被说成普遍结论。`SKILL.md` 列出了这些错误类型，供核对时逐条排查。

## 安装

```bash
npx skills add OpenGHz/chat-share-skill -s chat-share -g
```

也可以直接克隆为 Claude Code 用户级 skill：

```bash
git clone git@github.com:OpenGHz/chat-share-skill.git ~/.claude/skills/chat-share
```

之后把分享链接发给 agent 即可，例如：“整理到 docs：https://www.kimi.com/share/…”。

## 命令行用法

```bash
python3 -I scripts/fetch_share.py URL [-o OUTDIR] [--thinking] [--download-cached]
```

默认输出到 `<临时目录>/chat-share/<平台>-<分享 id>/`：

| 文件 | 内容 |
| --- | --- |
| `conversation.md` | 全部轮次。行内引用换成 `[S<k>]`，每轮末尾列出本轮的来源：URL、模型引用的原句、缓存副本 |
| `sources.md` | 每次工具调用返回的全部结果，用于人工核对脚本没能解析的引用 |
| `cached/` | 加 `--download-cached` 时生成：Kimi 缓存的被引来源副本 |
| `raw.json` | 平台返回的原始数据，未作改动 |

加 `--thinking` 会输出模型的思考内容；不加时只记录思考内容的长度。

## 支持的平台

| 平台 | 接口 | 引用解析 |
| --- | --- | --- |
| DeepSeek | `GET /api/v0/share/content`，无需认证 | `[citation:N]` 对应 `cite_index` 为 N 的搜索结果 |
| Kimi（`kimi.com`、`kimi.moonshot.cn`、`kimi.ai`） | Connect RPC `ChatService/GetChatShare`；需要时申请匿名访客 token | `tools://<调用>#N`：网页搜索对应 id 为 N+1 的结果，网页抓取对应第 N 个结果 |

这些都是没有公开文档的内部接口，平台可能随时改动。[`PROVIDERS.md`](PROVIDERS.md) 记录了返回数据的结构、找到 Kimi 接口的步骤（包括从前端代码中解析 protobuf 服务描述符），以及如何接入新平台。

## 局限

- 只能抓取公开分享。脚本使用的匿名访问方式与网页本身相同。
- DeepSeek 搜索引用的解析参照了 [Convolvger](https://github.com/bilalmughal1/convolvger) 的解析器和测试数据，还没有在用到搜索的真实分享上验证过。
- 如果某条引用指向的结果不在分享数据里，脚本会标记为 `UNRESOLVED`，留给人工核对。

## 致谢

[Convolvger](https://github.com/bilalmughal1/convolvger)（MIT）记录了 DeepSeek 分享接口的数据结构，并为其他平台提供了适配代码。

## 许可证

[MIT](LICENSE)
