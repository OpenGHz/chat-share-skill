<div align="center">

# chat-share

**Turn a shared AI chat link into a fact-checked write-up, from a coding agent or straight from your shell.**

English | [简体中文](README.zh-CN.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Agent skill](https://img.shields.io/badge/agent-skill-6E56CF.svg)](#install)
[![stdlib only](https://img.shields.io/badge/python-stdlib--only-lightgrey.svg)](scripts/fetch_share.py)

</div>

Paste a `chat.deepseek.com/share/...` or `kimi.com/share/...` link. You get the full conversation, and every inline citation resolved to the page the model actually read. The skill then checks each claim against its primary source before writing anything down.

The repo has two parts, and each works on its own:

- **`scripts/fetch_share.py`** is a plain Python CLI. It uses only the standard library and needs no browser, cookies, or account.
- **`SKILL.md`** is the workflow: fetch, list the claims, verify each one against its primary source, then write up only what checks out, with a corrections table for the rest.

## Why this exists

Share pages and the answers in them both resist the naive approach:

- **A share page is an empty app shell.** Fetching it returns `<div id="app"></div>`. The conversation comes from an undocumented API (a REST call for DeepSeek, a Connect RPC for Kimi), and some Kimi shares answer "not found" until you get a guest token.
- **Kimi citations are pointers, not links.** An answer cites `tools://web_search:3#16`, an index into that tool call's results. The index is 0-based, while result ids start at 1. The script resolves each pointer to its URL and keeps the quoted text and Kimi's cached copy of the page. That cached copy is often the only way to read an OpenReview PDF that returns 403.
- **Answers drift from their sources.** Checking two real shares against the papers turned up a figure whose values were invented, a table read with its columns shifted, two ablation variants swapped, a real-robot-only number reported as an overall result, and a toy-experiment observation stated as a general finding. `SKILL.md` lists these patterns so that each claim gets checked for them.

## Install

```bash
npx skills add OpenGHz/chat-share-skill -s chat-share -g
```

Or clone it as a Claude Code user skill:

```bash
git clone git@github.com:OpenGHz/chat-share-skill.git ~/.claude/skills/chat-share
```

Then give your agent a share link, for example: "整理到 docs: https://www.kimi.com/share/…".

## CLI

```bash
python3 -I scripts/fetch_share.py URL [-o OUTDIR] [--thinking] [--download-cached]
```

By default it writes to `<tmp>/chat-share/<provider>-<share id>/`:

| File | Contents |
| --- | --- |
| `conversation.md` | Every turn. Inline citations become `[S<k>]`, and each turn ends with its sources: URL, quoted text, cached copy |
| `sources.md` | Every result of every tool call, for citations the script could not resolve |
| `cached/` | With `--download-cached`: Kimi's cached copies of cited sources |
| `raw.json` | The provider's response, untouched |

Pass `--thinking` to include the model's reasoning text. Without it, the transcript records only its length.

## Providers

| Provider | Endpoint | Citations |
| --- | --- | --- |
| DeepSeek | `GET /api/v0/share/content`, no auth | `[citation:N]` maps to the search result with `cite_index` N |
| Kimi (`kimi.com`, `kimi.moonshot.cn`, `kimi.ai`) | Connect RPC `ChatService/GetChatShare`; anonymous guest token when needed | `tools://<call>#N` maps to result id N+1 (web search) or position N (URL fetch) |

These endpoints are internal and undocumented, so they can change without notice. [`PROVIDERS.md`](PROVIDERS.md) records the payload shapes, the steps that found Kimi's endpoint (including decoding protobuf service descriptors from the web bundle), and how to add a provider.

## Limitations

- Only public shares. The script uses the same anonymous access the web page uses.
- DeepSeek's search-citation path follows [Convolvger](https://github.com/bilalmughal1/convolvger)'s parser and fixture, and has not yet been run on a real share that used search.
- When a citation points to a result the share does not include, the script marks it `UNRESOLVED` and leaves it for a manual check.

## Acknowledgements

[Convolvger](https://github.com/bilalmughal1/convolvger) (MIT) documents the DeepSeek share payload and has adapters for other providers.

## License

[MIT](LICENSE)
