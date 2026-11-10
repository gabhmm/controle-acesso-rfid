/**
 * Página de Monitoramento em Tempo Real (Segurança Privada)
 * Faz polling a cada 2 segundos em GET /api/eventos e GET /api/colaboradores
 */

function renderizarItemEvento(ev, destacarAlerta = false) {
  const classeAlerta = destacarAlerta ? `alert-${ev.resultado}` : "";
  const horaApenas = ev.data_hora.split(" ")[1] || ev.data_hora;
  return `
    <li class="event-item ${classeAlerta}">
      <div>
        <div style="font-weight: 600; font-size: 0.92rem;">
          ${ev.nome}
          <span class="mono" style="margin-left: 0.35rem; font-weight: 400;">${ev.tag_uid}</span>
        </div>
        <div style="font-size: 0.78rem; color: var(--text-secondary);">
          Horário: ${ev.data_hora} (ID #${ev.id})
        </div>
      </div>
      <div style="text-align: right;">
        <span class="badge badge-${ev.resultado}">${ev.resultado}</span>
        <div style="font-size: 0.75rem; color: var(--text-secondary); margin-top: 0.2rem;">${horaApenas}</div>
      </div>
    </li>
  `;
}

function preencherLista(elementId, eventos, msgVazio, destacarAlerta = false) {
  const ul = document.getElementById(elementId);
  if (!eventos.length) {
    ul.innerHTML = `<li class="empty-state">${msgVazio}</li>`;
    return;
  }
  ul.innerHTML = eventos.map((e) => renderizarItemEvento(e, destacarAlerta)).join("");
}

/**
 * Calcula quem está na sala seguindo a regra de api contratos.md:
 * "'Dentro da sala' = colaboradores cujo último evento do dia é ENTRADA."
 * E enriquece com o tempo diário retornado por /api/colaboradores.
 */
function renderizarPresentesNaSala(eventosHoje, colaboradores) {
  const container = document.getElementById("lista-na-sala");
  const mapaColab = new Map();
  colaboradores.forEach((c) => mapaColab.set(c.tag_uid.toUpperCase(), c));

  // Como eventosHoje vem do mais recente para o mais antigo,
  // o primeiro evento ENTRADA ou SAIDA visto para cada tag_uid é o último evento do dia daquele colaborador
  const ultimoEstadoPorTag = new Map();
  for (const ev of eventosHoje) {
    const tag = ev.tag_uid.toUpperCase();
    if ((ev.resultado === "ENTRADA" || ev.resultado === "SAIDA") && !ultimoEstadoPorTag.has(tag)) {
      ultimoEstadoPorTag.set(tag, ev);
    }
  }

  const presentes = [];
  for (const [tag, ultimoEv] of ultimoEstadoPorTag.entries()) {
    if (ultimoEv.resultado === "ENTRADA") {
      presentes.push({
        evento: ultimoEv,
        colab: mapaColab.get(tag) || null,
      });
    }
  }

  document.getElementById("kpi-na-sala").textContent = presentes.length;
  document.getElementById("badge-count-sala").textContent = `${presentes.length} presente(s)`;

  if (!presentes.length) {
    container.innerHTML = `<div class="empty-state" style="grid-column: 1 / -1;">Nenhum colaborador dentro da sala restrita no momento.</div>`;
    return;
  }

  container.innerHTML = presentes
    .map(({ evento, colab }) => {
      const cargo = colab ? colab.cargo : "Colaborador";
      const tempoHoje = colab ? Api.formatarDuracao(colab.tempo_hoje_segundos) : "--:--:--";
      const horaEntrada = evento.data_hora.split(" ")[1] || evento.data_hora;
      return `
        <div class="occupant-card">
          <div style="display: flex; justify-content: space-between; align-items: flex-start;">
            <div>
              <div style="font-weight: 700; font-size: 0.96rem;">${evento.nome}</div>
              <div style="font-size: 0.8rem; color: var(--text-secondary);">${cargo}</div>
            </div>
            <span class="mono">${evento.tag_uid}</span>
          </div>
          <div style="margin-top: 0.6rem; padding-top: 0.45rem; border-top: 1px solid var(--border-color); display: flex; justify-content: space-between; font-size: 0.78rem; color: var(--text-secondary);">
            <span>Entrou às <strong>${horaEntrada}</strong></span>
            <span>Hoje: <strong style="color: var(--success);">${tempoHoje}</strong></span>
          </div>
        </div>
      `;
    })
    .join("");
}

async function atualizarPainelMonitoramento() {
  try {
    const [eventos, colaboradores] = await Promise.all([
      Api.request("/api/eventos"),
      Api.request("/api/colaboradores"),
    ]);

    const entradas = eventos.filter((e) => e.resultado === "ENTRADA");
    const saidas = eventos.filter((e) => e.resultado === "SAIDA");
    const negados = eventos.filter((e) => e.resultado === "NEGADO");
    const invasoes = eventos.filter((e) => e.resultado === "INVASAO");
    const alertas = eventos.filter((e) => e.resultado === "INVASAO" || e.resultado === "NEGADO");

    // KPIs
    document.getElementById("kpi-entradas").textContent = entradas.length;
    document.getElementById("kpi-saidas").textContent = saidas.length;
    document.getElementById("kpi-negados").textContent = negados.length;
    document.getElementById("kpi-invasoes").textContent = invasoes.length;

    const badgeAlertas = document.getElementById("badge-count-alertas");
    badgeAlertas.textContent = `${alertas.length} alerta(s)`;
    badgeAlertas.style.animation = invasoes.length > 0 ? "pulse-danger 1.8s infinite" : "none";

    // Presentes na sala
    renderizarPresentesNaSala(eventos, colaboradores);

    // Listas filtradas
    preencherLista("lista-alertas", alertas, "Nenhum alerta de segurança registrado hoje.", true);
    preencherLista("lista-entradas", entradas, "Nenhuma entrada autorizada hoje.");
    preencherLista("lista-saidas", saidas, "Nenhuma saída registrada hoje.");
    preencherLista("lista-negados", negados, "Nenhuma tentativa negada hoje.", true);
    preencherLista("lista-invasoes", invasoes, "Nenhuma tentativa de invasão hoje.", true);

    const agora = new Date();
    document.getElementById("ultimo-sync").textContent = agora.toLocaleTimeString("pt-BR");
  } catch (err) {
    console.error("Erro no polling de monitoramento:", err);
  }
}

async function simularTag(tagUid) {
  if (!tagUid) return;
  const banner = document.getElementById("banner-validacao");
  try {
    const res = await Api.request("/api/validar", {
      method: "POST",
      body: JSON.stringify({ tag_uid: tagUid }),
    });

    const cores = {
      ENTRADA: { bg: "var(--success-bg)", cor: "#34d399", borda: "rgba(16,185,129,0.45)" },
      SAIDA: { bg: "var(--info-bg)", cor: "#60a5fa", borda: "rgba(59,130,246,0.45)" },
      NEGADO: { bg: "var(--warning-bg)", cor: "#fbbf24", borda: "rgba(245,158,11,0.45)" },
      INVASAO: { bg: "var(--danger-bg)", cor: "#f87171", borda: "rgba(239,68,68,0.55)" },
    };
    const estilo = cores[res.resultado] || cores.ENTRADA;

    banner.style.display = "block";
    banner.style.background = estilo.bg;
    banner.style.color = estilo.cor;
    banner.style.border = `1px solid ${estilo.borda}`;
    banner.textContent = `[${res.resultado}] Tag ${tagUid.toUpperCase()} → "${res.mensagem}"`;

    await atualizarPainelMonitoramento();
  } catch (err) {
    alert(err.message);
  }
}

document.getElementById("form-simular").addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = document.getElementById("input-tag-simular");
  const valor = input.value.trim().toUpperCase();
  if (valor) {
    await simularTag(valor);
    input.value = "";
  }
});

// Inicialização imediata e polling estrito a cada 2 segundos (2000 ms)
atualizarPainelMonitoramento();
setInterval(atualizarPainelMonitoramento, 2000);
