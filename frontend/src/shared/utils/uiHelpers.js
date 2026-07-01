export function summarizeAgentPrompt(prompt) {
  const text = String(prompt || '').trim();
  if (!text) return '暂未填写系统提示词。';
  return text.length > 68 ? text.slice(0, 68) + '...' : text;
}

export function getShortName(value, fallback) {
  const text = String(value || '').trim();
  if (!text) return fallback;
  return text.slice(0, 2).toUpperCase();
}

export function formatTime(value) {
  if (!value) return '--';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '--';
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date);
}
