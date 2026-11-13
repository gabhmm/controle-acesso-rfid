/**
 * Utilitários compartilhados de comunicação com a API do servidor (FastAPI)
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
      throw new Error(Api.mensagemDeErro(data, response.status));
    }
    return data;
  },
  escaparHtml(valor) {
  if (valor === null || valor === undefined) return "";
  const texto = String(valor);
  const mapa = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
  let resultado = "";
  for (const c of texto) {
    resultado += mapa[c] ?? c;
 
  }
  return resultado;
  },

  // O login responde {erro: "..."}; o FastAPI responde {detail: "..."} nos erros das rotas
  // e {detail: [{msg: "..."}]} quando um campo do formulário é inválido (422).
  mensagemDeErro(data, status) {
    if (data.erro) return data.erro;
    if (typeof data.detail === "string") return data.detail;
    if (Array.isArray(data.detail) && data.detail.length) {
      return data.detail.map((d) => `${(d.loc || []).slice(-1)[0] || "campo"}: ${d.msg}`).join("; ");
    }
    return `Erro HTTP ${status}`;
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
