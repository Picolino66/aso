/* Execução assíncrona (ADR-0067, MEL-31).
 *
 * Com ASO_EXECUCAO_ASSINCRONA=1, as rotas que acionam agentes respondem 202 com um job em
 * vez de segurar a requisição. `asoAguardarJob` acompanha o job por polling e devolve o mesmo
 * resultado que a rota síncrona devolveria (ou lança o erro do job), para as telas não
 * precisarem saber em que modo o runtime está. A cada consulta dispara `aso:job` no document
 * para quem quiser mostrar o andamento.
 */
(function () {
  var TERMINAIS = ['done', 'failed', 'cancelled'];

  function esperar(ms) {
    return new Promise(function (resolve) { setTimeout(resolve, ms); });
  }

  window.asoAguardarJob = async function (aceito, headers, opcoes) {
    var url = (aceito && aceito.acompanhar) || ('/v1/jobs/' + encodeURIComponent(aceito.job_id));
    var intervalo = (opcoes && opcoes.intervaloMs) || 1000;
    var h = {};
    if (headers && headers.Authorization) h.Authorization = headers.Authorization;
    for (;;) {
      var resposta = await fetch(url, { headers: h });
      if (!resposta.ok) {
        throw new Error('Não foi possível acompanhar a execução (HTTP ' + resposta.status + ').');
      }
      var job = await resposta.json();
      document.dispatchEvent(new CustomEvent('aso:job', { detail: job }));
      if (TERMINAIS.indexOf(job.status) >= 0) {
        if (job.status === 'done') return job.resultado;
        var prefixo = job.status === 'cancelled' ? 'Execução cancelada' : 'Execução falhou';
        throw new Error(job.erro ? prefixo + ': ' + job.erro : prefixo + '.');
      }
      await esperar(intervalo);
    }
  };

  // Resposta 202 de uma rota de execução → espera o job; qualquer outra passa direto.
  window.asoResolverResposta = function (status, corpo, headers) {
    if (status === 202 && corpo && corpo.job_id) return window.asoAguardarJob(corpo, headers);
    return corpo;
  };
})();
