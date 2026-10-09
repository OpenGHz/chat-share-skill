# Providers

Reference for `scripts/fetch_share.py`: each provider's endpoint, payload shape, and citation rule; how to rediscover an endpoint when a provider changes; how to add a provider. Facts dated 2026-10-09 unless noted.

## DeepSeek

- `GET https://chat.deepseek.com/api/v0/share/content?share_id=<id>`, no auth. The share page itself is an empty app shell.
- `data.biz_data`: `title`, `messages[]` with `message_id`, `parent_id`, `role` (`USER`/`ASSISTANT`), `fragments[]`.
- Fragment `type`: `REQUEST`, `RESPONSE` (text in `content`), `THINK`, `SEARCH` (`queries[].query`, `results[]` with `url`, `title`, `snippet`, `cite_index`).
- Citation: `[citation:N]` in a `RESPONSE` points to the result with `cite_index == N` in the same message. Taken from Convolvger's parser and fixture; not yet observed on a real share with search.
- A share can begin mid-thread: a first message whose `parent_id` is set means earlier turns were not shared.

## Kimi

- Connect RPC with JSON: `POST https://www.kimi.com/apiv2/kimi.gateway.chat.v1.ChatService/GetChatShare`, body `{"shareId": "<id>"}`, headers `Content-Type: application/json`, `Connect-Protocol-Version: 1`, `x-msh-platform: web`.
- Some shares answer 404 `REASON_CHAT_SHARE_NOT_FOUND` without a token (an Agent-mode share did; Convolvger reports others work tokenless). Guest token: `POST https://www.kimi.com/api/device/register` with header `x-msh-device-id: <random 19 digits>` and body `{"device_id": <same>}` returns `access_token`; send it as `Authorization: Bearer`. The device id is required (422 without it).
- `share`: `chat.name`, `messages[]` with `role` and `blocks[]`. Block kinds: `text.content`, `think.content`, `tool` (`toolCallId`, `name`, `args` as a JSON string, `contents[]` of `searchResult {id, base {title, url, snippet}}` or `webOpenUrl {url}`), and `stage`/`multiStage` (progress markers, skipped).
- Citation: `<REF>cite✦tools://<toolCallId>#<N>:~:text=<quote start>...<quote end></REF>`.
  - `web_search`: N is 0-based and maps to the result with `searchResult.id == N + 1`. Results with id `"0"` were never shown to the model. Checked on 14 citations against sources matched by hand.
  - `fetch_urls`: N indexes `contents`.
  - The quote is the model's excerpt of page text it saw. Stored snippets are short, so a quote absent from the snippet is normal.
- `downloadUrl` (on `kimi-web-img.kimi.ai`) is Kimi's cached copy of the page or PDF; it works where OpenReview answers 403. A fetched URL's cached copy may sit on an earlier search result with the same URL; the script copies it across.

## Rediscovering an endpoint

Share pages are app shells (`<div id="app"></div>`), so the conversation comes from an API the page's JavaScript calls. The route that found Kimi's:

1. From the page HTML, take the entry script (`src=".../index-*.js"`). In it, find chunk names containing `share` (string literals such as `assets/Share-*.js`) and fetch them.
2. In the share chunk, find the call that loads the conversation (Kimi: `chatService.getChatShare({shareId, messageOrder})`) and the module it imports the service from.
3. Connect / gRPC-web services embed their protobuf `FileDescriptorProto` as a base64 string in `*_pb-*.js` chunks. Decode it to get `<package>.<Service>/<Method>`:

   ```python
   def varint(b, i):
       r = s = 0
       while True:
           c = b[i]; i += 1; r |= (c & 0x7f) << s; s += 7
           if c < 0x80: return r, i
   def fields(b):                       # -> [(field_no, value)]
       i, out = 0, []
       while i < len(b):
           k, i = varint(b, i); f, w = k >> 3, k & 7
           if w == 0: v, i = varint(b, i)
           elif w == 2: l, i = varint(b, i); v = b[i:i + l]; i += l
           elif w == 1: v = b[i:i + 8]; i += 8
           elif w == 5: v = b[i:i + 4]; i += 4
           else: raise ValueError(w)
           out.append((f, v))
       return out
   # FileDescriptorProto: 2 = package, 6 = service; ServiceDescriptorProto: 1 = name, 2 = method;
   # MethodDescriptorProto: 1 = name, 2 = input type, 3 = output type.
   ```

4. In the request module, find the base URL per namespace (Kimi: `"kimi"` maps to `/apiv2`) and the header builder (`getHeaders`) for required headers.
5. POST JSON with `Connect-Protocol-Version: 1`. If it answers not_found or unauthenticated for a share that opens in a browser, look for an anonymous token flow in the token module (Kimi: `/api/device/register`).

For REST providers (DeepSeek), the share chunk names the path directly; search it for `share`.

## Adding a provider

Add `fetch_<p>(url) -> (share_id, raw, data)` and `parse_<p>(data, want_thinking) -> (title, turns, tools, warnings)`, then register its hosts in `PROVIDERS`.

- A turn is `{role, text, thinking[], cites[]}`.
- A cite is `{ref, quote, title, url, snippet, download, quote_in_snippet}`.
- A tool is `{id, name, args[], results[]}`.

Replace inline citation markers in `text` with `[S<k>]`, numbered per turn.

[Convolvger](https://github.com/bilalmughal1/convolvger) (MIT, early-stage) has working adapters for ChatGPT, Gemini, Grok, Qwen, and Claude to crib endpoints from. Claude shares need a browser step there.
