/* Sidebar compartilhada das 16 seções (wf §2.4) — ADR-0036.
 *
 * Segundo módulo JS compartilhado do projeto (depois de `header.js`, ADR-0035)
 * — 16 itens de navegação, cada um numa página própria; duplicar isso em 16
 * arquivos seria pior que este arquivo. Só as 16 páginas novas montam a
 * sidebar; as 4 páginas legadas (`/ui/`, `/ui/nova`, `/ui/detalhe`,
 * `/ui/console`) continuam como estavam — cada uma mistura conteúdo de várias
 * seções, então não há uma "seção ativa" única e honesta para destacar nelas.
 */
(function () {
  'use strict';

  // Ordem exata do wf §2.4.
  const ITENS = [
    { slug: 'dashboard', label: 'Dashboard', icon: '📊' },
    { slug: 'demandas', label: 'Demandas', icon: '📋' },
    { slug: 'esteira', label: 'Esteira', icon: '🛤️' },
    { slug: 'kanban', label: 'Kanban', icon: '🗂️' },
    { slug: 'agentes', label: 'Agentes', icon: '🤖' },
    { slug: 'modelos', label: 'Modelos', icon: '🧠' },
    { slug: 'documentos', label: 'Documentos', icon: '📄' },
    { slug: 'aprovacoes', label: 'Aprovações', icon: '✅' },
    { slug: 'execucoes', label: 'Execuções', icon: '▶️' },
    { slug: 'testes', label: 'Testes', icon: '🧪' },
    { slug: 'code-reviews', label: 'Code Reviews', icon: '🔍' },
    { slug: 'implantacoes', label: 'Implantações', icon: '🚀' },
    { slug: 'incidentes', label: 'Incidentes', icon: '🚨' },
    { slug: 'auditoria', label: 'Auditoria', icon: '🗒️' },
    { slug: 'metricas', label: 'Métricas', icon: '📈' },
    { slug: 'configuracoes', label: 'Configurações', icon: '⚙️' },
  ];

  function secaoDaRota() {
    const partes = location.pathname.split('/').filter(Boolean); // ["ui", "<secao>"]
    return partes[0] === 'ui' ? partes[1] || '' : '';
  }

  function mount(container, opts) {
    opts = opts || {};
    const ativa = opts.active || secaoDaRota();
    container.innerHTML =
      '<ul class="sidebar-nav">' +
      ITENS.map(function (item) {
        return (
          '<li><a class="sidebar-item' +
          (item.slug === ativa ? ' active' : '') +
          '" href="/ui/' +
          item.slug +
          '"><span class="ic">' +
          item.icon +
          '</span>' +
          item.label +
          '</a></li>'
        );
      }).join('') +
      '</ul>';

    if (!document.getElementById('sidebar-toggle')) {
      const toggle = document.createElement('button');
      toggle.id = 'sidebar-toggle';
      toggle.className = 'sidebar-toggle ghost sm';
      toggle.type = 'button';
      toggle.setAttribute('aria-label', 'Alternar navegação');
      toggle.textContent = '☰';
      toggle.addEventListener('click', function () {
        container.classList.toggle('sidebar-open');
      });
      document.body.appendChild(toggle);
    }
  }

  window.ASOSidebar = { mount: mount, ITENS: ITENS };
})();
