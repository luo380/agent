# 前端 service 说明

## `frontend/src/shared/services/useApiClient.js`

这是前端唯一的共享请求封装，目前由 `frontend/src/App.vue` 使用。

### `parseApiResponse(response)`

1. 读取 response body 为文本。
2. 有内容时尝试解析 JSON。
3. 如果服务端返回 HTML 或其他非 JSON，抛出带前 120 个字符的错误，便于发现代理/路由问题。
4. 如果 HTTP 状态不是 2xx，优先使用 `detail` 或 `message`，否则使用状态码和状态文本。
5. 成功时返回解析后的 JSON 数据；空响应返回 `null`。

### `apiJson(path, options = {})`

- 调用 `getToken()` 取得 token。
- 有 token 时添加 `Authorization: Bearer ...`。
- 有 body 时默认添加 `Content-Type: application/json`。
- 合并调用方自定义 headers。
- 以 `apiPrefix + path` 发起 `fetch`，默认前缀是 `/api`。
- 统一交给 `parseApiResponse` 处理。

它不负责业务状态、重试、SSE 流式解析或文件上传；这些能力若需要，应在更贴近具体功能的 service 中增加，避免继续把 `App.vue` 变成总入口。

### `fetchCurrentUser(token)`

直接请求 `/auth/me`，显式使用传入 token，适合应用启动时恢复当前用户。

### 返回对象

```js
{
  parseApiResponse,
  apiJson,
  fetchCurrentUser,
}
```

调用方因此不需要重复写鉴权 header、JSON 解析和错误判断。

## 与后端的对应关系

普通 JSON 请求可通过 `apiJson` 调用 API；但聊天和 RAG 流式接口返回 SSE，不能直接套用 `response.json()`。当前后端的 SSE 事件包括普通聊天的 `start/delta/done/error`，RAG 还会有 `context_ready` 等事件，前端需要用 `response.body.getReader()` 或 `EventSource` 按事件流解析。

