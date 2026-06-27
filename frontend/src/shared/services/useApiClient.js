export function useApiClient(getToken, apiPrefix = '/api') {
  async function parseApiResponse(response) {
    const rawText = await response.text();
    let data = null;
    if (rawText) {
      try {
        data = JSON.parse(rawText);
      } catch {
        throw new Error('接口返回了非 JSON 内容：' + rawText.slice(0, 120));
      }
    }
    if (!response.ok) {
      throw new Error(data?.detail || data?.message || ('请求失败：' + response.status + ' ' + response.statusText));
    }
    return data;
  }

  async function apiJson(path, options = {}) {
    const token = typeof getToken === 'function' ? getToken() : '';
    const headers = {
      ...(token ? { Authorization: 'Bearer ' + token } : {}),
      ...(options.body ? { 'Content-Type': 'application/json' } : {}),
      ...(options.headers || {}),
    };
    const response = await fetch(apiPrefix + path, { ...options, headers });
    return parseApiResponse(response);
  }

  async function fetchCurrentUser(token) {
    const response = await fetch(apiPrefix + '/auth/me', {
      headers: { Authorization: 'Bearer ' + token },
    });
    return parseApiResponse(response);
  }

  return {
    parseApiResponse,
    apiJson,
    fetchCurrentUser,
  };
}