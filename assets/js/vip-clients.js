/**
 * Локальная «база» VIP-клиентов (localStorage). Без уровней — единый список.
 */
(function (global) {
  const STORAGE_KEY = 'fnr_vip_clients';

  function read() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return [];
      const data = JSON.parse(raw);
      return Array.isArray(data) ? data : [];
    } catch {
      return [];
    }
  }

  function write(list) {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(list));
  }

  function uid() {
    return 'v' + Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
  }

  const VipClients = {
    getAll() {
      return read();
    },

    add(entry) {
      const list = read();
      const row = {
        id: uid(),
        name: String(entry.name || '').trim(),
        company: String(entry.company || '').trim(),
        phone: String(entry.phone || '').trim(),
        email: String(entry.email || '').trim(),
        notes: String(entry.notes || '').trim(),
        createdAt: new Date().toISOString(),
      };
      list.unshift(row);
      write(list);
      return row;
    },

    update(id, entry) {
      const list = read();
      const i = list.findIndex((r) => r.id === id);
      if (i === -1) return false;
      list[i] = {
        ...list[i],
        name: String(entry.name || '').trim(),
        company: String(entry.company || '').trim(),
        phone: String(entry.phone || '').trim(),
        email: String(entry.email || '').trim(),
        notes: String(entry.notes || '').trim(),
      };
      write(list);
      return true;
    },

    remove(id) {
      const list = read().filter((r) => r.id !== id);
      write(list);
    },
  };

  global.FnrVipClients = VipClients;
})(typeof window !== 'undefined' ? window : globalThis);
