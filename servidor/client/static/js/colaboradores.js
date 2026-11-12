/**
 * Lógica de CRUD para Gerenciamento de Colaboradores e Permissões RFID
 */

let listaColaboradores = [];

function exibirMensagem(texto, erro = false) {
  const box = document.getElementById("msg-feedback");
  box.textContent = texto;
  box.style.display = "block";
  box.style.background = erro ? "var(--danger-bg)" : "var(--success-bg)";
  box.style.color = erro ? "#fca5a5" : "#34d399";
  box.style.border = erro
    ? "1px solid rgba(239, 68, 68, 0.4)"
    : "1px solid rgba(16, 185, 129, 0.4)";

  setTimeout(() => {
    box.style.display = "none";
  }, 4000);
}

async function carregarColaboradores() {
  try {
    listaColaboradores = await Api.request("/api/colaboradores");
    renderizarTabela();
  } catch (err) {
    exibirMensagem(err.message || "Erro ao carregar colaboradores", true);
  }
}

function renderizarTabela() {
  const tbody = document.getElementById("tabela-colaboradores");
  if (!listaColaboradores.length) {
    tbody.innerHTML = `<tr><td colspan="10" class="empty-state">Nenhum colaborador cadastrado.</td></tr>`;
    return;
  }

  tbody.innerHTML = listaColaboradores
    .map((c) => {
      const badgeAcesso = c.acesso_sala
        ? `<span class="badge badge-ENTRADA">✓ Autorizado</span>`
        : `<span class="badge badge-NEGADO">✕ Sem Acesso</span>`;

      const badgeAtivo = c.ativo
        ? `<span class="badge badge-SAIDA">Ativo</span>`
        : `<span class="badge badge-INVASAO" style="animation:none;">Inativo</span>`;

      const badgeSala = c.na_sala
        ? `<span class="badge badge-ENTRADA">🟢 Dentro da Sala</span>`
        : c.entrou_hoje
          ? `<span style="color: var(--text-secondary); font-size: 0.83rem;">Saiu (Esteve hoje)</span>`
          : `<span style="color: var(--text-secondary); font-size: 0.83rem;">Não entrou hoje</span>`;

      return `
        <tr>
          <td>#${c.id}</td>
          <td style="font-weight: 600;">${c.nome}</td>
          <td><span class="mono">${c.matricula}</span></td>
          <td>${c.cargo}</td>
          <td><span class="mono">${c.tag_uid}</span></td>
          <td>${badgeAcesso}</td>
          <td>${badgeAtivo}</td>
          <td>${badgeSala}</td>
          <td><span class="mono">${Api.formatarDuracao(c.tempo_hoje_segundos)}</span></td>
          <td style="text-align: right; white-space: nowrap;">
            <button class="btn btn-secondary btn-sm" onclick="togglePermissaoRapida(${c.id})" title="Alternar Permissão da Sala">
              ${c.acesso_sala ? "Revogar Sala" : "Liberar Sala"}
            </button>
            <button class="btn btn-secondary btn-sm" onclick="abrirModalEditar(${c.id})">Editar</button>
            <button class="btn btn-danger btn-sm" onclick="excluirColaborador(${c.id}, '${c.nome.replace(/'/g, "\\'")}')">Excluir</button>
          </td>
        </tr>
      `;
    })
    .join("");
}

function abrirModalNovo() {
  document.getElementById("modal-titulo").textContent = "Cadastrar Novo Colaborador";
  document.getElementById("colab-id").value = "";
  document.getElementById("colab-nome").value = "";
  document.getElementById("colab-matricula").value = "";
  document.getElementById("colab-tag").value = "";
  document.getElementById("colab-cargo").value = "";
  document.getElementById("colab-acesso").checked = true;
  document.getElementById("colab-ativo").checked = true;
  document.getElementById("modal-colab").classList.add("open");
}

function abrirModalEditar(id) {
  const colab = listaColaboradores.find((item) => item.id === id);
  if (!colab) return;

  document.getElementById("modal-titulo").textContent = `Editar Colaborador #${colab.id}`;
  document.getElementById("colab-id").value = colab.id;
  document.getElementById("colab-nome").value = colab.nome;
  document.getElementById("colab-matricula").value = colab.matricula;
  document.getElementById("colab-tag").value = colab.tag_uid;
  document.getElementById("colab-cargo").value = colab.cargo;
  document.getElementById("colab-acesso").checked = Boolean(colab.acesso_sala);
  document.getElementById("colab-ativo").checked = Boolean(colab.ativo);
  document.getElementById("modal-colab").classList.add("open");
}

function fecharModal() {
  document.getElementById("modal-colab").classList.remove("open");
}

async function togglePermissaoRapida(id) {
  const colab = listaColaboradores.find((item) => item.id === id);
  if (!colab) return;

  try {
    await Api.request(`/api/colaboradores/${id}`, {
      method: "PUT",
      body: JSON.stringify({
        ...colab,
        acesso_sala: !colab.acesso_sala,
      }),
    });
    exibirMensagem(`Permissão de sala atualizada para ${colab.nome}.`);
    await carregarColaboradores();
  } catch (err) {
    exibirMensagem(err.message, true);
  }
}

async function excluirColaborador(id, nome) {
  if (!confirm(`Tem certeza que deseja excluir o colaborador "${nome}"?`)) {
    return;
  }
  try {
    await Api.request(`/api/colaboradores/${id}`, { method: "DELETE" });
    exibirMensagem(`Colaborador "${nome}" removido com sucesso.`);
    await carregarColaboradores();
  } catch (err) {
    exibirMensagem(err.message, true);
  }
}

document.getElementById("form-colab").addEventListener("submit", async (e) => {
  e.preventDefault();
  const id = document.getElementById("colab-id").value;
  const payload = {
    nome: document.getElementById("colab-nome").value.trim(),
    matricula: document.getElementById("colab-matricula").value.trim(),
    tag_uid: document.getElementById("colab-tag").value.trim().toUpperCase(),
    cargo: document.getElementById("colab-cargo").value.trim(),
    acesso_sala: document.getElementById("colab-acesso").checked,
    ativo: document.getElementById("colab-ativo").checked,
  };

  try {
    if (id) {
      await Api.request(`/api/colaboradores/${id}`, {
        method: "PUT",
        body: JSON.stringify(payload),
      });
      exibirMensagem(`Colaborador "${payload.nome}" atualizado com sucesso.`);
    } else {
      await Api.request("/api/colaboradores", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      exibirMensagem(`Colaborador "${payload.nome}" cadastrado com sucesso.`);
    }
    fecharModal();
    await carregarColaboradores();
  } catch (err) {
    exibirMensagem(err.message, true);
  }
});

// Inicialização e atualização periódica a cada 5s na tela de colaboradores
carregarColaboradores();
setInterval(carregarColaboradores, 5000);
