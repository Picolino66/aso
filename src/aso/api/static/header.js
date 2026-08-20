/* Header compartilhado das 4 páginas de /ui/* (wf §2.3, 9 elementos) — ADR-0035.
 *
 * Primeiro módulo JS compartilhado do projeto (as 4 páginas eram 100%
 * autocontidas até aqui, ver ADR-0034) — necessário porque isto é
 * funcionalidade nova com dados ao vivo, não um reskin: duplicar 9 elementos
 * e sua lógica de polling em 4 lugares seria pior que este arquivo.
 *
 * Cada página chama `ASOHeader.mount(container, opts)` UMA VEZ, no início do
 * seu próprio <script>, antes de qualquer `getElementById` que dependa dos
 * elementos do header (login, projeto, etc.) — `mount` escreve o HTML de
 * forma síncrona (innerHTML), então o restante do script da página encontra
 * os elementos normalmente depois da chamada.
 *
 * `token()`/localStorage('aso_token') continuam sendo a fonte de verdade do
 * Bearer token — cada página mantém sua própria função `token()` local para
 * suas chamadas de API; este arquivo só gerencia o campo/botão de login.
 */
(function () {
  'use strict';

  function token() {
    return localStorage.getItem('aso_token') || '';
  }

  async function api(path) {
    const headers = {};
    if (token()) headers.Authorization = 'Bearer ' + token();
    const response = await fetch(path, { headers });
    if (!response.ok) return null;
    return response.json();
  }

  function esc(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  const TEMPLATE =
    '<h1>⚙️ ASO Runtime</h1>' +
    '<span class="sub" id="hdr-sub"></span>' +
    '<span class="sub" id="hdr-projeto" hidden></span>' +
    '<span class="sub" id="hdr-ambiente" hidden></span>' +
    '<span class="pill" id="hdr-execucoes" title="Execuções ativas">Execuções: …</span>' +
    '<span class="pill" id="hdr-falhas" title="Falhas">Falhas: …</span>' +
    '<span class="pill" id="hdr-aprovacoes" title="Aprovações pendentes">Aprovações: …</span>' +
    '<span class="spacer"></span>' +
    '<span id="hdr-extra"></span>' +
    '<div class="hdr-busca">' +
    '<input id="hdr-busca-input" placeholder="Buscar demanda, card, documento…" autocomplete="off">' +
    '<div class="hdr-dropdown" id="hdr-busca-resultados" hidden></div>' +
    '</div>' +
    '<div class="hdr-busca">' +
    '<button class="ghost sm" id="hdr-notif" title="Notificações" type="button">🔔<span id="hdr-notif-count"></span></button>' +
    '<div class="hdr-dropdown" id="hdr-notif-painel" hidden></div>' +
    '</div>' +
    '<span class="sub" id="hdr-usuario" title="Perfil do usuário"></span>' +
    '<input id="token" aria-label="Token Bearer" placeholder="token (Bearer)" style="width:160px">' +
    '<button id="login" class="ghost sm" type="button">Entrar</button>';

  function toggle(painel, mostrar) {
    document.querySelectorAll('.hdr-dropdown').forEach(function (node) {
      if (node !== painel) node.hidden = true;
    });
    painel.hidden = mostrar === undefined ? !painel.hidden : !mostrar;
  }

  async function carregarResumo(container, opts) {
    const resumo = await api(
      '/v1/header-summary' + (opts.projectId ? '?project_id=' + encodeURIComponent(opts.projectId) : '')
    );
    if (!resumo) return;
    container.querySelector('#hdr-execucoes').textContent = 'Execuções: ' + resumo.execucoes_ativas;
    container.querySelector('#hdr-falhas').textContent = 'Falhas: ' + resumo.falhas;
    container.querySelector('#hdr-falhas').className = 'pill' + (resumo.falhas > 0 ? ' err' : '');
    container.querySelector('#hdr-aprovacoes').textContent = 'Aprovações: ' + resumo.aprovacoes_pendentes;
    container.querySelector('#hdr-aprovacoes').className = 'pill' + (resumo.aprovacoes_pendentes > 0 ? ' warn' : '');
    const contagem = resumo.aprovacoes_pendentes;
    container.querySelector('#hdr-notif-count').textContent = contagem > 0 ? ' ' + contagem : '';
  }

  async function carregarNotificacoes(container, opts) {
    const painel = container.querySelector('#hdr-notif-painel');
    const aprovacoes =
      (await api(
        '/v1/approvals?status=pending' + (opts.projectId ? '&project_id=' + encodeURIComponent(opts.projectId) : '')
      )) || [];
    if (!aprovacoes.length) {
      painel.innerHTML = '<div class="muted" style="padding:10px">Sem pendências.</div>';
      return;
    }
    painel.innerHTML = aprovacoes
      .slice(0, 10)
      .map(function (a) {
        return (
          '<a class="hdr-dropdown-item" href="/ui/detalhe?id=' +
          encodeURIComponent(a.orchestration_id) +
          '">' +
          esc(a.action) +
          ' <span class="muted">— ' +
          esc(a.reason || 'aprovação pendente') +
          '</span></a>'
        );
      })
      .join('');
  }

  function wireBusca(container, opts) {
    const input = container.querySelector('#hdr-busca-input');
    const resultados = container.querySelector('#hdr-busca-resultados');
    let timer = null;
    input.addEventListener('input', function () {
      clearTimeout(timer);
      const termo = input.value.trim();
      if (!termo) {
        resultados.hidden = true;
        return;
      }
      timer = setTimeout(async function () {
        const url =
          '/v1/search?q=' +
          encodeURIComponent(termo) +
          (opts.projectId ? '&project_id=' + encodeURIComponent(opts.projectId) : '');
        const itens = (await api(url)) || [];
        if (!itens.length) {
          resultados.innerHTML = '<div class="muted" style="padding:10px">Nada encontrado.</div>';
        } else {
          resultados.innerHTML = itens
            .map(function (item) {
              return (
                '<a class="hdr-dropdown-item" href="/ui/detalhe?id=' +
                encodeURIComponent(item.orchestration_id) +
                '"><span class="pill">' +
                esc(item.tipo) +
                '</span> ' +
                esc(item.titulo) +
                '</a>'
              );
            })
            .join('');
        }
        toggle(resultados, true);
      }, 300);
    });
    document.addEventListener('click', function (ev) {
      if (!container.contains(ev.target)) resultados.hidden = true;
    });
  }

  async function carregarProjetoEAmbiente(container, opts) {
    if (!opts.orchestrationId) return;
    const orch = await api('/v1/orchestrations/' + encodeURIComponent(opts.orchestrationId));
    if (!orch) return;
    const ambienteEl = container.querySelector('#hdr-ambiente');
    ambienteEl.textContent = 'Ambiente: ' + (orch.deploy_environment || '—');
    ambienteEl.hidden = false;
    if (orch.project_id) {
      const projeto = await api('/v1/projects/' + encodeURIComponent(orch.project_id));
      const projetoEl = container.querySelector('#hdr-projeto');
      if (projeto) {
        projetoEl.textContent = 'Projeto: ' + projeto.name;
        projetoEl.hidden = false;
      }
    }
  }

  async function carregarUsuario(container) {
    const me = await api('/v1/me');
    if (!me) return;
    container.querySelector('#hdr-usuario').textContent = me.actor + ' · ' + me.role;
  }

  function mount(container, opts) {
    opts = opts || {};
    container.innerHTML = TEMPLATE;
    if (opts.subtitulo) container.querySelector('#hdr-sub').textContent = opts.subtitulo;
    if (opts.extraHtml) container.querySelector('#hdr-extra').innerHTML = opts.extraHtml;

    const tokenInput = container.querySelector('#token');
    tokenInput.value = token();
    container.querySelector('#login').addEventListener('click', function () {
      localStorage.setItem('aso_token', tokenInput.value.trim());
      location.reload();
    });

    const notifBtn = container.querySelector('#hdr-notif');
    const notifPainel = container.querySelector('#hdr-notif-painel');
    notifBtn.addEventListener('click', function () {
      toggle(notifPainel);
      if (!notifPainel.hidden) carregarNotificacoes(container, opts);
    });

    wireBusca(container, opts);
    carregarUsuario(container);
    carregarProjetoEAmbiente(container, opts);
    carregarResumo(container, opts);
    setInterval(function () {
      carregarResumo(container, opts);
    }, 20000);
  }

  window.ASOHeader = { mount: mount, token: token };
})();
