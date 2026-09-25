/* Módulo compartilhado de acesso à API do console — ADR-0078 (MEL-55).
 *
 * As 20 páginas repetiam as mesmas quatro funções (`token`, `api`, `esc` e, em algumas, o
 * polling do 202 da fila): quatro cópias divergiram em como tratavam 403/409, e corrigir a
 * mensagem de erro exigia editar arquivo por arquivo. Aqui fica uma implementação só.
 *
 * Uso:
 *   const corpo = await ASOApi.api('/v1/executors');                    // GET
 *   await ASOApi.api('/v1/executors', { method: 'POST', body: {...} }); // body objeto ou string
 *   ASOApi.esc(texto)                                                   // escapa para HTML
 * O 202 da fila (ADR-0067) é resolvido sozinho: `api` acompanha o job e devolve o resultado que
 * a rota síncrona devolveria (`{ seguirJob: false }` desliga).
 *
 * `api` devolve o corpo já em JSON e levanta `Error` com a mensagem que o operador precisa ler:
 * 403 vira "requer papel …" (ADR-0057) e 409 traz o `detail` da governança, que é a razão real
 * da recusa (gate reprovado, estratégia pendente, versão concorrente…).
 */
(function () {
  'use strict';

  function token() {
    return localStorage.getItem('aso_token') || '';
  }

  function esc(valor) {
    return String(valor == null ? '' : valor).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function mensagemDeErro(status, corpo) {
    const detalhe = (corpo && (corpo.detail || corpo.message)) || '';
    if (status === 401) return 'Sem token: informe o token no header (' + detalhe + ')';
    if (status === 403) {
      return 'Ação recusada (403): requer papel com permissão' + (detalhe ? ' — ' + detalhe : '');
    }
    if (status === 409) return 'Governança recusou (409): ' + (detalhe || 'estado não permite');
    if (status === 404) return 'Não encontrado (404)' + (detalhe ? ': ' + detalhe : '');
    return detalhe || 'HTTP ' + status;
  }

  async function api(path, opts) {
    opts = Object.assign({}, opts || {});
    const headers = Object.assign({ 'content-type': 'application/json' }, opts.headers || {});
    if (token()) headers.Authorization = 'Bearer ' + token();
    if (opts.body && typeof opts.body !== 'string') opts.body = JSON.stringify(opts.body);
    const resposta = await fetch(path, Object.assign({}, opts, { headers: headers }));
    let corpo = null;
    try {
      corpo = await resposta.json();
    } catch (e) {
      corpo = null;
    }
    if (!resposta.ok) {
      const erro = new Error(mensagemDeErro(resposta.status, corpo));
      erro.status = resposta.status;
      erro.corpo = corpo;
      throw erro;
    }
    if (corpo && typeof corpo === 'object' && !Array.isArray(corpo)) {
      Object.defineProperty(corpo, '_status', { value: resposta.status, enumerable: false });
    }
    // 202 de rota de execução → espera o job e devolve o resultado (ADR-0067). `seguirJob:false`
    // desliga isso (usado pelo próprio polling, para não recorrer infinitamente).
    if (resposta.status === 202 && corpo && corpo.job_id && opts.seguirJob !== false) {
      return acompanharJob(corpo, opts.job);
    }
    return corpo;
  }

  const TERMINAIS = ['done', 'failed', 'cancelled'];

  /* Acompanha um job da fila (ADR-0067) até o fim e devolve o MESMO resultado que a rota
   * síncrona devolveria — as telas não precisam saber em que modo o runtime está. Job
   * `failed`/`cancelled` levanta com o erro registrado, em vez de silêncio. A cada consulta
   * dispara `aso:job` no `document`, para quem quiser mostrar o andamento.
   */
  async function acompanharJob(aceito, opts) {
    opts = opts || {};
    if (!aceito || !aceito.job_id) return aceito;
    const url = aceito.acompanhar || '/v1/jobs/' + encodeURIComponent(aceito.job_id);
    const intervalo = opts.intervaloMs || 1000;
    for (;;) {
      const job = await api(url, { seguirJob: false });
      document.dispatchEvent(new CustomEvent('aso:job', { detail: job }));
      if (TERMINAIS.indexOf(job.status) >= 0) {
        if (job.status === 'done') return job.resultado;
        const prefixo = job.status === 'cancelled' ? 'Execução cancelada' : 'Execução falhou';
        throw new Error(job.erro ? prefixo + ': ' + job.erro : prefixo + '.');
      }
      await new Promise(function (ok) {
        setTimeout(ok, intervalo);
      });
    }
  }

  window.ASOApi = {
    token: token,
    api: api,
    esc: esc,
    mensagemDeErro: mensagemDeErro,
    acompanharJob: acompanharJob,
  };
})();
