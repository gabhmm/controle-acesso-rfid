/**
 * Utilitários compartilhados de comunicação com a API do Servidor Flask
 */

const Api = {
  async request(url, options = {}) {
    const config = {
      headers: { "Content-Type": "application/json" },
      ...options,
    };
    const response = await fetch(url, config);
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.erro || `Erro HTTP ${response.status}`);
    }
    return data;
  },

  formatarDuracao(segundosTotais) {
    const seg = Math.max(0, Number(segundosTotais) || 0);
    const h = Math.floor(seg / 3600);
    const m = Math.floor((seg % 3600) / 60);
    const s = Math.floor(seg % 60);
    const pad = (n) => String(n).padStart(2, "0");
    return `${pad(h)}h ${pad(m)}m ${pad(s)}s`;
  },

  async logout() {
    await fetch("/logout", { method: "POST" });
    window.location.href = "/login";
  },
};
