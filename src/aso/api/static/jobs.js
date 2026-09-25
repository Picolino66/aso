/* Compatibilidade: o polling de jobs (ADR-0067) mora em `aso-api.js` desde a ADR-0078 (MEL-55).
 *
 * Este arquivo continua existindo enquanto páginas antigas o carregam; ele só delega para o
 * módulo compartilhado, para não haver duas implementações do mesmo polling. Sai junto com as
 * páginas legadas.
 */
(function () {
  'use strict';

  function exigirModulo() {
    if (!window.ASOApi) throw new Error('Carregue /ui/aso-api.js antes de /ui/jobs.js.');
    return window.ASOApi;
  }

  window.asoAguardarJob = function (aceito, _headers, opcoes) {
    return exigirModulo().acompanharJob(aceito, opcoes);
  };

  window.asoResolverResposta = function (status, corpo, _headers) {
    if (status === 202 && corpo && corpo.job_id) return exigirModulo().acompanharJob(corpo);
    return corpo;
  };
})();
