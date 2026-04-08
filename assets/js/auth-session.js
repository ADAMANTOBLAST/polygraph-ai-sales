/**
 * Модуль сессии админки (каркас).
 *
 * Сейчас: проверка «вошёл ли пользователь» через sessionStorage.
 * Дальше: заменить на ответ вашего бэкенда или OAuth Bitrix24 (user.current и т.п.),
 * хранить безопасный токен, не пароли в браузере.
 */
(function (global) {
  const STORAGE_KEY = 'fnr_admin_session';

  function getSession() {
    try {
      const raw = sessionStorage.getItem(STORAGE_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch {
      return null;
    }
  }

  /** Есть ли валидная сессия (заглушка по сроку действия). */
  function isLoggedIn() {
    const s = getSession();
    if (!s || !s.token || !s.expiresAt) return false;
    return Date.now() < s.expiresAt;
  }

  /**
   * Временная запись сессии после «успешного» входа.
   * TODO: вызывать после реального API login / Bitrix, подставлять token с сервера.
   */
  function setSessionStub(payload) {
    const session = {
      token: payload.token || 'stub-' + Date.now(),
      user: payload.user || 'admin',
      expiresAt: payload.expiresAt || Date.now() + 8 * 60 * 60 * 1000, // 8 часов
    };
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(session));
  }

  function logout() {
    sessionStorage.removeItem(STORAGE_KEY);
  }

  /** Вызвать в начале admin/index.html: незалогиненных уводим на страницу входа. */
  function requireAdminPage() {
    if (!isLoggedIn()) {
      global.location.replace('login.html');
    }
  }

  global.FnrAuth = {
    STORAGE_KEY,
    getSession,
    isLoggedIn,
    setSessionStub,
    logout,
    requireAdminPage,
  };
})(typeof window !== 'undefined' ? window : globalThis);
