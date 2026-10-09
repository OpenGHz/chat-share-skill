#!/usr/bin/env python3
"""Fetch a shared AI chat (DeepSeek, Kimi) into a transcript with resolved citations.

Usage:
    python3 -I fetch_share.py URL [-o OUTDIR] [--thinking] [--download-cached]

Writes to OUTDIR (default /tmp/chat-share/<provider>-<share id>/):
    raw.json         the provider's response, untouched
    conversation.md  every turn; inline citations become [S<k>] with a source list per turn
    sources.md       every search/fetch result per tool call (for unresolved citations)
    cached/          with --download-cached: provider-cached copies of cited sources
Prints a one-line summary: turns, citations resolved/total, warnings.
Standard library only.
"""

import argparse
import json
import os
import random
import re
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/129.0 Safari/537.36")


def http(url, data=None, headers=None, timeout=60):
    """Return (status, body bytes). JSON-encodes dict data and POSTs it."""
    hdrs = {"User-Agent": UA, "Accept": "application/json, */*"}
    hdrs.update(headers or {})
    body = None
    if data is not None:
        body = json.dumps(data).encode()
        hdrs.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=body, headers=hdrs,
                                 method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def share_id_of(url):
    parts = [p for p in urllib.parse.urlparse(url).path.split("/") if p]
    if "share" not in parts or parts[-1] == "share":
        sys.exit(f"not a share link: {url}")
    return parts[-1]


# ---------------------------------------------------------------- DeepSeek

def fetch_deepseek(url):
    sid = share_id_of(url)
    api = f"https://chat.deepseek.com/api/v0/share/content?share_id={sid}"
    status, body = http(api, headers={"Referer": url})
    if status != 200:
        sys.exit(f"DeepSeek API {status}: {body[:300]!r}")
    raw = json.loads(body)
    data = (raw.get("data") or {}).get("biz_data")
    if not data or not data.get("messages"):
        sys.exit(f"DeepSeek returned no messages: {body[:300]!r}")
    return sid, raw, data


def parse_deepseek(data, want_thinking):
    title = data.get("title") or ""
    turns, tools, warnings = [], [], []
    msgs = data["messages"]
    if msgs and msgs[0].get("parent_id") not in (None, 0, -1):
        warnings.append(f"share starts mid-conversation (first message parent_id="
                        f"{msgs[0].get('parent_id')}); earlier turns were not shared")
    for m in msgs:
        role = "user" if m.get("role") == "USER" else "assistant"
        text_parts, results, thinking = [], {}, []
        frags = m.get("fragments") or []
        if not frags and m.get("content"):  # older share format
            frags = [{"type": "RESPONSE" if role == "assistant" else "REQUEST",
                      "content": m["content"]}]
            if m.get("thinking_content"):
                frags.insert(0, {"type": "THINK", "content": m["thinking_content"]})
            if m.get("search_results"):
                frags.insert(0, {"type": "SEARCH", "results": m["search_results"]})
        for f in frags:
            kind = f.get("type")
            if kind in ("REQUEST", "RESPONSE"):
                text_parts.append(f.get("content") or "")
            elif kind == "SEARCH":
                tid = f"search:{len(tools) + 1}"
                res = f.get("results") or []
                tools.append({"id": tid, "name": "search",
                              "args": [q.get("query") for q in f.get("queries") or []],
                              "results": [{"id": r.get("cite_index"), "title": r.get("title"),
                                           "url": r.get("url"), "snippet": r.get("snippet")}
                                          for r in res]})
                for r in res:
                    if r.get("cite_index") is not None:
                        results[int(r["cite_index"])] = r
                text_parts.append(f"> [tool {tid}] search: "
                                  + "; ".join(tools[-1]["args"]) + f" ({len(res)} results)")
            elif kind == "THINK":
                c = f.get("content") or ""
                thinking.append(c if want_thinking else f"[thinking: {len(c)} chars]")
            else:
                text_parts.append(f"> [fragment {kind}]")
        text = "\n\n".join(text_parts)
        cites = []

        def repl(mo):
            n = int(mo.group(1))
            r = results.get(n)
            cites.append({"ref": f"citation:{n}", "quote": "",
                          "title": r.get("title") if r else None,
                          "url": r.get("url") if r else None,
                          "snippet": r.get("snippet") if r else None,
                          "download": None, "quote_in_snippet": None})
            return f"[S{len(cites)}]"

        text = re.sub(r"\[citation:(\d+)\]", repl, text)
        turns.append({"role": role, "text": text, "thinking": thinking, "cites": cites})
    return title, turns, tools, warnings


# ---------------------------------------------------------------- Kimi

KIMI_RPC = "/apiv2/kimi.gateway.chat.v1.ChatService/GetChatShare"


def kimi_token(host, device_id):
    status, body = http(f"{host}/api/device/register", data={"device_id": device_id},
                        headers={"x-msh-platform": "web", "x-msh-version": "2.3.0",
                                 "x-msh-device-id": device_id, "Origin": host})
    if status != 200:
        sys.exit(f"Kimi device register {status}: {body[:300]!r}")
    return json.loads(body).get("access_token")


def fetch_kimi(url):
    sid = share_id_of(url)
    netloc = urllib.parse.urlparse(url).netloc
    hosts = ["https://www.kimi.com"]
    if netloc and "kimi.com" not in netloc:
        hosts.insert(0, f"https://{netloc}")
    last = None
    for host in hosts:
        device_id = str(random.randint(7 * 10**18, 76 * 10**17))
        base = {"Connect-Protocol-Version": "1", "x-msh-platform": "web",
                "x-msh-version": "2.3.0", "x-msh-device-id": device_id,
                "Origin": host, "Referer": url}
        status, body = http(host + KIMI_RPC, data={"shareId": sid}, headers=base)
        if status in (401, 403, 404):  # anonymous shares sometimes need a guest token
            token = kimi_token(host, device_id)
            status, body = http(host + KIMI_RPC, data={"shareId": sid},
                                headers={**base, "Authorization": f"Bearer {token}"})
        if status == 200:
            raw = json.loads(body)
            if (raw.get("share") or {}).get("messages"):
                return sid, raw, raw["share"]
        last = (host, status, body[:300])
    sys.exit(f"Kimi GetChatShare failed: {last!r}")


KIMI_CITE = re.compile(r"<REF>(.*?)</REF>", re.S)
KIMI_ONE = re.compile(r"tools://([a-z_]+:\d+)#(\d+)(?::~:text=([^✦]*))?")


def _norm(s):
    return re.sub(r"\s+", " ", s or "").strip().lower()


def _kimi_result(x):
    sr = x.get("searchResult") or x.get("webOpenUrl") or {}
    base = sr.get("base") or sr
    blob = json.dumps(x, ensure_ascii=False)
    dl = re.search(r'"downloadUrl": "([^"]+)"', blob)
    return {"id": sr.get("id"), "title": base.get("title"), "url": base.get("url"),
            "snippet": base.get("snippet"), "download": dl.group(1) if dl else None}


def parse_kimi(share, want_thinking):
    title = (share.get("chat") or {}).get("name") or ""
    turns, tools, warnings = [], [], []
    tool_index = {}
    for m in share["messages"]:  # index all tool calls first: citations may point back
        for b in m.get("blocks") or []:
            if "tool" in b:
                t = b["tool"]
                tool_index[t.get("toolCallId")] = [_kimi_result(x) for x in t.get("contents") or []]
    # A fetched URL often has its cached copy only on an earlier search result.
    cached = {r["url"]: r["download"] for rs in tool_index.values() for r in rs if r["download"]}
    for rs in tool_index.values():
        for r in rs:
            r["download"] = r["download"] or cached.get(r["url"])

    def resolve(tid, n, quote):
        results = tool_index.get(tid) or []
        if tid.startswith("web_search"):
            # Kimi's citation index is 0-based; searchResult ids are 1-based.
            # Results with id "0" were not shown to the model.
            hit = next((r for r in results if str(r["id"]) == str(n + 1)), None)
        else:
            hit = results[n] if n < len(results) else None
        frags = [f for f in (_norm(q) for q in (quote or "").split("...")) if len(f) > 15]
        if hit is None and frags:  # fall back to quote text matching
            hit = next((r for r in results if any(f[:40] in _norm(r["snippet"]) for f in frags)), None)
        in_snip = None
        if hit is not None and frags:
            in_snip = any(f[:40] in _norm(hit["snippet"]) for f in frags)
        return hit, in_snip

    for m in share["messages"]:
        role = m.get("role", "assistant")
        parts, thinking, cites = [], [], []
        for b in m.get("blocks") or []:
            if "text" in b:
                c = b["text"].get("content", "") if isinstance(b["text"], dict) else str(b["text"])

                def repl(mo):
                    marks = []
                    for tid, n, quote in KIMI_ONE.findall(mo.group(1)):
                        quote = urllib.parse.unquote(quote or "")
                        hit, in_snip = resolve(tid, int(n), quote)
                        cites.append({"ref": f"{tid}#{n}", "quote": quote,
                                      "title": hit and hit["title"], "url": hit and hit["url"],
                                      "snippet": hit and hit["snippet"],
                                      "download": hit and hit["download"],
                                      "quote_in_snippet": in_snip})
                        marks.append(f"[S{len(cites)}]")
                    return "".join(marks) or mo.group(0)

                parts.append(KIMI_CITE.sub(repl, c))
            elif "think" in b:
                c = b["think"].get("content", "") if isinstance(b["think"], dict) else str(b["think"])
                thinking.append(c if want_thinking else f"[thinking: {len(c)} chars]")
            elif "tool" in b:
                t = b["tool"]
                try:
                    args = json.loads(t.get("args") or "{}")
                except json.JSONDecodeError:
                    args = {"raw": t.get("args")}
                shown = args.get("queries") or args.get("urls") or args
                res = tool_index.get(t.get("toolCallId")) or []
                tools.append({"id": t.get("toolCallId"), "name": t.get("name"),
                              "args": shown if isinstance(shown, list) else [json.dumps(shown, ensure_ascii=False)],
                              "results": res})
                parts.append(f"> [tool {t.get('toolCallId')}] " + "; ".join(map(str, tools[-1]["args"]))
                             + f" ({len(res)} results)")
        turns.append({"role": role, "text": "\n\n".join(p for p in parts if p),
                      "thinking": thinking, "cites": cites})
    return title, turns, tools, warnings


# ---------------------------------------------------------------- output

PROVIDERS = {"chat.deepseek.com": (fetch_deepseek, parse_deepseek, "deepseek"),
             "kimi.com": (fetch_kimi, parse_kimi, "kimi"),
             "kimi.moonshot.cn": (fetch_kimi, parse_kimi, "kimi"),
             "kimi.ai": (fetch_kimi, parse_kimi, "kimi")}


def pick(url):
    host = urllib.parse.urlparse(url).netloc.lower()
    for key, val in PROVIDERS.items():
        if host == key or host.endswith("." + key):
            return val
    sys.exit(f"unsupported provider: {host} (see PROVIDERS.md, 'Adding a provider')")


def write_outputs(outdir, url, provider, title, turns, tools, warnings, download):
    os.makedirs(outdir, exist_ok=True)
    lines = [f"# {title or 'Shared conversation'}", "",
             f"- source: {url}", f"- provider: {provider}", f"- turns: {len(turns)}"]
    lines += [f"- WARNING: {w}" for w in warnings] + [""]
    n_cites = n_res = 0
    for i, t in enumerate(turns):
        lines += [f"## Turn {i + 1} — {t['role']}", ""]
        lines += [f"<details><summary>thinking</summary>\n\n{th}\n\n</details>\n" if not th.startswith("[thinking:")
                  else f"_{th}_\n" for th in t["thinking"]]
        lines += [t["text"], ""]
        if t["cites"]:
            lines += ["**Sources cited in this turn**", ""]
            for k, c in enumerate(t["cites"], 1):
                n_cites += 1
                n_res += bool(c["url"])
                # Stored snippets are short, so a miss proves nothing; only a hit is reported.
                head = (f"- [S{k}] `{c['ref']}` → {c['title'] or '?'} — {c['url'] or 'UNRESOLVED'}"
                        + (" (quote matches stored snippet)" if c["quote_in_snippet"] else ""))
                lines.append(head)
                if c["quote"]:
                    lines.append(f"  - quoted: «{c['quote']}»")
                if c["download"]:
                    lines.append(f"  - cached copy: {c['download']}")
            lines.append("")
    with open(os.path.join(outdir, "conversation.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))

    src = [f"# Tool results — {title}", ""]
    for t in tools:
        src += [f"## {t['id']} ({t['name']})", "", "args: " + "; ".join(map(str, t["args"])), ""]
        for r in t["results"]:
            src.append(f"- id={r['id']} {r['title'] or ''} — {r['url']}"
                       + (f" (cached: {r['download']})" if r.get("download") else ""))
        src.append("")
    with open(os.path.join(outdir, "sources.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(src))

    fetched = 0
    if download:
        cdir = os.path.join(outdir, "cached")
        os.makedirs(cdir, exist_ok=True)
        seen = set()
        for t in turns:
            for c in t["cites"]:
                if c["download"] and c["download"] not in seen:
                    seen.add(c["download"])
                    status, body = http(c["download"].replace(" ", "%20"))
                    if status == 200:
                        name = re.sub(r"[^A-Za-z0-9._-]+", "_", urllib.parse.urlparse(c["url"]).path)[-80:] or "file"
                        with open(os.path.join(cdir, f"{len(seen):02d}{name}"), "wb") as fh:
                            fh.write(body)
                        fetched += 1
    return n_cites, n_res, fetched


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("url")
    ap.add_argument("-o", "--outdir")
    ap.add_argument("--thinking", action="store_true", help="include model thinking text")
    ap.add_argument("--download-cached", action="store_true",
                    help="download provider-cached copies of cited sources (Kimi)")
    a = ap.parse_args()
    fetch, parse, provider = pick(a.url)
    sid, raw, data = fetch(a.url)
    outdir = a.outdir or os.path.join(tempfile.gettempdir(), "chat-share", f"{provider}-{sid}")
    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, "raw.json"), "w", encoding="utf-8") as fh:
        json.dump(raw, fh, ensure_ascii=False, indent=1)
    title, turns, tools, warnings = parse(data, a.thinking)
    n_cites, n_res, fetched = write_outputs(outdir, a.url, provider, title, turns, tools,
                                            warnings, a.download_cached)
    print(f"{outdir}: {len(turns)} turns, {len(tools)} tool calls, "
          f"citations resolved {n_res}/{n_cites}"
          + (f", cached files {fetched}" if a.download_cached else "")
          + "".join(f"\nWARNING: {w}" for w in warnings))


if __name__ == "__main__":
    main()
