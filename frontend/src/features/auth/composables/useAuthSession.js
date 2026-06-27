import { reactive, ref } from 'vue';

export function useAuthSession(options) {
  const {
    storageTokenKey,
    apiJson,
    fetchCurrentUser,
    enterWorkspace,
  } = options;

  const activeTab = ref('login');
  const currentView = ref('auth');
  const sessionChecking = ref(true);
  const registerSubmitting = ref(false);
  const loginSubmitting = ref(false);
  const registerMessage = ref('');
  const registerMessageType = ref('info');
  const loginMessage = ref('');
  const loginMessageType = ref('info');
  const registerPreview = ref('等待注册提交...');
  const loginPreview = ref('等待登录提交...');
  const currentToken = ref('');
  const currentUser = ref(null);

  const registerForm = reactive({
    name: '',
    email: '',
    password: '',
    confirmPassword: '',
    agreement: false,
  });

  const loginForm = reactive({
    email: '',
    password: '',
    rememberMe: true,
  });

  function setRegisterMessage(message, type = 'info') {
    registerMessage.value = message;
    registerMessageType.value = type;
  }

  function setLoginMessage(message, type = 'info') {
    loginMessage.value = message;
    loginMessageType.value = type;
  }

  function clearStoredSession() {
    localStorage.removeItem(storageTokenKey);
  }

  function validateRegisterForm() {
    if (!registerForm.name.trim()) return '请输入名称';
    if (!registerForm.email.trim()) return '请输入邮箱';
    if (registerForm.password.length < 8) return '密码至少需要 8 位';
    if (registerForm.password !== registerForm.confirmPassword) return '两次输入的密码不一致';
    if (!registerForm.agreement) return '请先确认当前测试协议';
    return '';
  }

  function validateLoginForm() {
    if (!loginForm.email.trim()) return '请输入登录邮箱';
    if (loginForm.password.length < 8) return '请输入正确的登录密码';
    return '';
  }

  async function restoreSession() {
    const storedToken = localStorage.getItem(storageTokenKey);
    if (!storedToken) {
      sessionChecking.value = false;
      return;
    }
    try {
      const user = await fetchCurrentUser(storedToken);
      currentToken.value = storedToken;
      currentUser.value = user;
      await enterWorkspace();
    } catch {
      clearStoredSession();
      currentToken.value = '';
      currentUser.value = null;
      currentView.value = 'auth';
      activeTab.value = 'login';
      setLoginMessage('登录状态已失效，请重新登录。', 'warning');
    } finally {
      sessionChecking.value = false;
    }
  }

  async function submitRegister() {
    const errorMessage = validateRegisterForm();
    if (errorMessage) {
      setRegisterMessage(errorMessage, 'error');
      return;
    }
    registerSubmitting.value = true;
    setRegisterMessage('正在创建账号，请稍候...', 'info');
    registerPreview.value = 'Submitting register request...';
    try {
      const result = await apiJson('/auth/register', {
        method: 'POST',
        body: JSON.stringify({
          name: registerForm.name.trim(),
          email: registerForm.email.trim(),
          password: registerForm.password,
        }),
      });
      registerPreview.value = JSON.stringify(result, null, 2);
      setRegisterMessage('注册成功，现在可以直接切换到登录继续。', 'success');
      loginForm.email = registerForm.email.trim();
      registerForm.name = '';
      registerForm.email = '';
      registerForm.password = '';
      registerForm.confirmPassword = '';
      registerForm.agreement = false;
      activeTab.value = 'login';
    } catch (error) {
      const m = error?.message || '注册失败，请检查后端接口状态';
      registerPreview.value = JSON.stringify({ error: m }, null, 2);
      setRegisterMessage(m, 'error');
    } finally {
      registerSubmitting.value = false;
    }
  }

  async function submitLogin() {
    const errorMessage = validateLoginForm();
    if (errorMessage) {
      setLoginMessage(errorMessage, 'error');
      return;
    }
    loginSubmitting.value = true;
    setLoginMessage('正在登录，请稍候...', 'info');
    loginPreview.value = 'Submitting login request...';
    try {
      const result = await apiJson('/auth/login', {
        method: 'POST',
        body: JSON.stringify({
          email: loginForm.email.trim(),
          password: loginForm.password,
        }),
      });
      const loginData = result?.data || {};
      currentToken.value = loginData.access_token || '';
      currentUser.value = loginData.user || null;
      loginPreview.value = JSON.stringify(result, null, 2);
      if (currentToken.value) {
        localStorage.setItem(storageTokenKey, currentToken.value);
      } else {
        clearStoredSession();
      }
      setLoginMessage('登录成功，正在进入会话工作台...', 'success');
      loginForm.password = '';
      await enterWorkspace();
    } catch (error) {
      const m = error?.message || '登录失败，请检查后端接口状态';
      loginPreview.value = JSON.stringify({ error: m }, null, 2);
      setLoginMessage(m, 'error');
    } finally {
      loginSubmitting.value = false;
    }
  }

  return {
    activeTab,
    currentView,
    sessionChecking,
    registerSubmitting,
    loginSubmitting,
    registerMessage,
    registerMessageType,
    loginMessage,
    loginMessageType,
    registerPreview,
    loginPreview,
    currentToken,
    currentUser,
    registerForm,
    loginForm,
    setRegisterMessage,
    setLoginMessage,
    clearStoredSession,
    restoreSession,
    submitRegister,
    submitLogin,
  };
}