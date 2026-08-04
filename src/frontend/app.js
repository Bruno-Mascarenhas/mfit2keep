// Interface do mfit2keep. Sem framework e sem build: o alvo é alguém que só
// quer preencher dois campos e clicar.

// O token vem na URL e sobe em cabeçalho customizado. Uma página maliciosa até
// consegue fazer POST em localhost, mas não lê a URL nem manda esse cabeçalho.
const TOKEN = new URLSearchParams(location.search).get("t") || "";

const $ = (id) => document.getElementById(id);

async function chamar(rota, corpo) {
  const resposta = await fetch(rota, {
    method: corpo === undefined ? "GET" : "POST",
    headers: { "X-Token": TOKEN, "Content-Type": "application/json" },
    body: corpo === undefined ? undefined : JSON.stringify(corpo),
  });
  const dados = await resposta.json().catch(() => ({ erro: "Resposta inesperada." }));
  if (!resposta.ok) throw new Error(dados.erro || `Falhou (${resposta.status}).`);
  return dados;
}

/** Roda a ação mostrando progresso e erro no lugar certo, sem travar a tela. */
async function comEstado(botao, alvo, mensagemOk, acao) {
  const estado = $(alvo);
  botao.disabled = true;
  estado.textContent = "…";
  estado.className = "estado";
  try {
    const resultado = await acao();
    estado.textContent = resultado?.mensagem || mensagemOk;
    estado.className = "estado ok";
    return resultado;
  } catch (erro) {
    estado.textContent = erro.message;
    estado.className = "estado erro";
    return null;
  } finally {
    botao.disabled = false;
  }
}

function pintarEstado(estado) {
  if (!estado) return;

  // Só preenche o que está vazio: não sobrescreve o que a pessoa está digitando.
  if (!$("mfit_email").value) $("mfit_email").value = estado.mfit_email;
  if (!$("google_email").value) $("google_email").value = estado.google_email;

  $("passo-conta").classList.toggle("pronto", estado.tem_senha && !!estado.mfit_email);
  $("passo-keep").classList.toggle("pronto", estado.tem_token_keep);
  $("passo-proteger").classList.toggle("pronto", estado.senha_cifrada);

  if (estado.tem_senha) {
    $("mfit_password").placeholder = "salva — deixe em branco para manter";
  }
  if (estado.tem_token_keep) {
    $("estado-keep").textContent = `conectado (${estado.token_keep})`;
    $("estado-keep").className = "estado ok";
  }

  const proteger = $("proteger");
  if (estado.senha_cifrada) {
    proteger.disabled = true;
    $("estado-proteger").textContent = "senha já protegida";
    $("estado-proteger").className = "estado ok";
  } else if (!estado.cifragem_disponivel) {
    proteger.disabled = true;
    $("estado-proteger").textContent = `indisponível neste sistema (${estado.cifragem_nome})`;
  }

  $("resumo").textContent = `Configuração salva em ${estado.env_file}`;
}

$("salvar").addEventListener("click", async (evento) => {
  const estado = await comEstado(evento.target, "estado-conta", "salvo", () =>
    chamar("/api/config", {
      mfit_email: $("mfit_email").value,
      mfit_password: $("mfit_password").value,
      google_email: $("google_email").value,
    }),
  );
  if (estado) {
    $("mfit_password").value = "";
    pintarEstado(estado);
  }
});

$("conectar").addEventListener("click", async (evento) => {
  const estado = await comEstado(evento.target, "estado-keep", "conectado!", () =>
    chamar("/api/keep-login", {
      oauth_token: $("oauth_token").value,
      google_email: $("google_email").value,
    }),
  );
  if (estado) {
    $("oauth_token").value = "";
    pintarEstado(estado);
  }
});

$("proteger").addEventListener("click", async (evento) => {
  const estado = await comEstado(evento.target, "estado-proteger", "protegida", () =>
    chamar("/api/proteger", {}),
  );
  if (estado) pintarEstado(estado);
});

$("buscar").addEventListener("click", async (evento) => {
  const dados = await comEstado(evento.target, "estado-sync", "", () => chamar("/api/rotinas", {}));
  if (!dados) return;

  const seletor = $("rotina");
  seletor.innerHTML = "";
  for (const rotina of dados.rotinas) {
    const opcao = document.createElement("option");
    opcao.value = rotina.id;
    opcao.textContent = rotina.fim ? `${rotina.nome} (até ${rotina.fim})` : rotina.nome;
    seletor.append(opcao);
  }

  const achou = dados.rotinas.length > 0;
  seletor.hidden = !achou;
  $("sincronizar").hidden = !achou;
  $("estado-sync").textContent = achou
    ? `${dados.rotinas.length} rotina(s) encontrada(s)`
    : "nenhuma rotina encontrada nesta conta";
  $("estado-sync").className = achou ? "estado ok" : "estado";
});

$("sincronizar").addEventListener("click", async (evento) => {
  const dados = await comEstado(evento.target, "estado-sync", "pronto!", () =>
    chamar("/api/sync", { routine_id: $("rotina").value, destino: "keep" }),
  );
  if (!dados) return;

  const corpo = $("resultado").querySelector("tbody");
  corpo.innerHTML = "";
  for (const nota of dados.notas) {
    const linha = corpo.insertRow();
    const titulo = linha.insertCell();
    if (nota.onde.startsWith("http")) {
      const link = document.createElement("a");
      link.href = nota.onde;
      link.target = "_blank";
      link.rel = "noopener";
      link.textContent = nota.titulo;
      titulo.append(link);
    } else {
      titulo.textContent = nota.titulo;
    }
    linha.insertCell().textContent = nota.acao;
  }
  $("resultado").hidden = dados.notas.length === 0;
  $("passo-sync").classList.add("pronto");
});

chamar("/api/estado")
  .then(pintarEstado)
  .catch((erro) => {
    $("resumo").textContent = `Não consegui falar com o app: ${erro.message}`;
  });
