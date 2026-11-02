import json
import math
import random
import subprocess
import sys
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

PASTA = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PASTA))
import robo_roleta as r


def padrao(jogo, chave):
    return next(p for p in r.catalogo_pesquisa(jogo) if p.chave == chave)


def giros(numeros):
    return [r.Giro.a_partir_do_numero(n) for n in numeros]


def historico(numeros):
    inicio = datetime(2026, 11, 2, 15, tzinfo=timezone(timedelta(hours=-3)))
    return [r.RegistroPesquisa(str(i+1), "mesa-teste", g, inicio+timedelta(seconds=i), "informado")
            for i, g in enumerate(giros(numeros))]


@pytest.mark.parametrize("familia,alvos,p", [
    ("cor", (r.PRETO,), 18/37), ("duzia", (1, 3), 24/37),
    ("coluna", (2, 3), 24/37), ("paridade", (0,), 18/37), ("metade", (1,), 18/37),
])
def test_enumeracao_roleta_margem_e_acerto(familia, alvos, p):
    mat = r.matematica_pesquisa(r.AlvoPesquisa(familia, alvos), r.ConfigPesquisa(protecao=1.0))
    assert mat["chance_alvo"] == pytest.approx(p)
    assert mat["roi_teorico"] == pytest.approx(-1/37)


def test_duas_duzias_superam_60_com_prejuizo():
    cfg = r.ConfigPesquisa()
    alvo = r.AlvoPesquisa("duzia", (1, 2))
    liquidacoes = [r.liquidar_pesquisa(g, alvo, cfg) for g in giros(range(37))]
    assert sum(a for a, _, _ in liquidacoes)/37 > .60
    assert sum(lucro for _, lucro, _ in liquidacoes) == pytest.approx(-20.0)


@pytest.mark.parametrize("lado,p,roi", [(r.PLAYER, 575/1296, -14.6/1296),
                                         (r.BANKER, 575/1296, -14.6/1296),
                                         (r.EMPATE, 146/1296, -58/1296)])
def test_enumeracao_exata_bacbo(lado, p, roi):
    mat = r.matematica_pesquisa(r.AlvoPesquisa("bacbo", (lado,)), r.ConfigPesquisa())
    assert mat["chance_alvo"] == pytest.approx(p)
    assert mat["roi_teorico"] == pytest.approx(roi)


@pytest.mark.parametrize("soma,pagamento", sorted(r.PAGA_EMPATE.items()))
def test_todos_os_pagamentos_de_empate(soma, pagamento):
    rodada = r.RodadaBacBo.do_resultado("E", soma)
    acerto, lucro, aposta = r.liquidar_pesquisa(rodada, r.AlvoPesquisa("bacbo", ("E",)), r.ConfigPesquisa())
    assert acerto and lucro == 10 * pagamento and aposta == 10


def test_empate_desconhecido_sem_protecao_tem_retorno_conhecido():
    rodada = r.RodadaBacBo.do_resultado("E")
    assert r.liquidar_pesquisa(rodada, r.AlvoPesquisa("bacbo", ("P",)), r.ConfigPesquisa()) == (False, -1, 10)


@pytest.mark.parametrize("alvo,protecao", [("P", 1), ("E", 0)])
def test_empate_desconhecido_nao_inventa_lucro(alvo, protecao):
    rodada = r.RodadaBacBo.do_resultado("E")
    assert r.liquidar_pesquisa(rodada, r.AlvoPesquisa("bacbo", (alvo,)), r.ConfigPesquisa(protecao=protecao))[1] is None


def test_sinal_apura_exclusivamente_rodada_seguinte():
    # Três vermelhos seguidos e um preto. Inverter no 3º acerta SEMPRE no 4º.
    registros = historico([1, 3, 5, 2]*100)
    rel = r.analisar_pesquisa(registros, "roleta", r.ConfigPesquisa(minimo_sinais=30),
                              [padrao("roleta", "cor_inv3")])
    linha = rel["tabela"][0]
    assert [linha[f]["entradas"] for f in ("treino", "validacao", "teste")] == [50, 25, 25]
    assert all(linha[f]["acerto"] == 1 for f in ("treino", "validacao", "teste"))


def test_escolha_no_treino_independe_do_futuro():
    rng = random.Random(123)
    treino = [rng.randrange(37) for _ in range(2000)]
    cauda_a, cauda_b = [1, 3, 5, 2]*500, [2, 4, 6, 1]*500
    cfg = r.ConfigPesquisa(minimo_sinais=30)
    rel_a = r.analisar_pesquisa(historico(treino+cauda_a), "roleta", cfg)
    rel_b = r.analisar_pesquisa(historico(treino+cauda_b), "roleta", cfg)
    assert rel_a["selecionado_no_treino"] == rel_b["selecionado_no_treino"]
    assert [x["treino"] for x in rel_a["tabela"]] == [x["treino"] for x in rel_b["tabela"]]


def test_dados_simulados_nao_comprovam_vantagem_real():
    registros = historico([1, 3, 5, 2]*2500)
    for fonte in ("simulado", "historico_informado"):
        dados = registros if fonte == "simulado" else [r.RegistroPesquisa(x.identificador, x.mesa, x.evento, x.horario, "simulado") for x in registros]
        rel = r.analisar_pesquisa(dados, "roleta", r.ConfigPesquisa(minimo_sinais=30), [padrao("roleta", "cor_inv3")], fonte)
        assert rel["tabela"][0]["criterios_numericos"]
        assert rel["dados_simulados"]
        assert not rel["criterios_atendidos_no_historico"]


def test_metadados_insuficientes_nao_validam_origem():
    registros = [r.RegistroPesquisa(x.identificador, x.mesa, x.evento) for x in historico([1, 3, 5, 2]*2500)]
    rel = r.analisar_pesquisa(registros, "roleta", r.ConfigPesquisa(minimo_sinais=30), [padrao("roleta", "cor_inv3")])
    assert rel["tabela"][0]["criterios_numericos"]
    assert not rel["metadados_completos"]
    assert not rel["criterios_atendidos_no_historico"]


def test_importador_preserva_repeticoes_e_remove_somente_id_duplicado():
    dados = b"id_rodada;mesa;numero\n1;mesa-a;7\n2;mesa-a;7\n2;mesa-a;7\n"
    registros, avisos = r.importar_historico_pesquisa(dados, "roleta")
    assert [x.evento.numero for x in registros] == [7, 7]
    assert any("duplicada" in a for a in avisos)


@pytest.mark.parametrize("dados,trecho", [
    (b"id_rodada;numero\n1;7\n1;8\n", "conflitantes"),
    (b"mesa;numero\na;7\nb;8\n", "Mesas diferentes"),
    (b"horario;numero\n2026-11-02T16:00:00-03:00;7\n2026-11-02T15:00:00-03:00;8\n", "fora de ordem"),
    (b"horario;numero\n;7\n2026-11-02T15:00:00-03:00;8\n", "todos os hor"),
    ("Número;Padrão;Apostado (R$)\n7;cor;10\n".encode(), "relatório de entradas"),
    (b"numero\n37\n", "inválido"),
    (b"numero\n7.5\n", "Linha 2"),
    (b"numero;numero\n7;8\n", "colunas repetidas"),
])
def test_importador_rejeita_dados_inadequados(dados, trecho):
    with pytest.raises(ValueError, match=trecho):
        r.importar_historico_pesquisa(dados, "roleta")


def test_exportacao_importacao_reproduz_historico_e_hash():
    dados = historico([7, 7, 0, 36]*100)
    rec, avisos = r.importar_historico_pesquisa(r.csv_historico_pesquisa(dados, "roleta"), "roleta")
    assert not avisos
    assert r.csv_historico_pesquisa(dados, "roleta") == r.csv_historico_pesquisa(rec, "roleta")
    assert r.analisar_pesquisa(dados, "roleta")["sha256_historico"] == r.analisar_pesquisa(rec, "roleta")["sha256_historico"]


def test_intervalo_wilson_exemplo_nist():
    # NIST: 26/200, limite inferior unilateral 95% ~=0,09577.
    inferior, _ = r.intervalo_wilson(26, 200, .10)
    assert inferior == pytest.approx(.09577, abs=.00001)
    assert r.intervalo_wilson(0, 0) == (0, 1)
    assert r.intervalo_wilson(70, 100, .0001)[0] < r.intervalo_wilson(70, 100)[0]


def test_metricas_incompletas_e_queda_desde_pico():
    met = r.MetricasPesquisa()
    for lucro in (10, -5, 3, -20, 10):
        met.registrar(lucro > 0, lucro, 10)
    assert met.queda_maxima == 22
    assert met.maior_sequencia_perdas == 1
    mat = r.matematica_pesquisa(r.AlvoPesquisa("cor", (r.PRETO,)), r.ConfigPesquisa())
    met.registrar(False, None, 10)
    resumo = met.resumo(mat, .01)
    assert resumo["roi"] is None and resumo["lucro"] is None and resumo["queda_maxima"] is None
    assert resumo["liquidacoes_incompletas"] == 1


def test_stop_loss_impede_proxima_entrada():
    cfg = r.ConfigPesquisa(valor_por_alvo=100, exposicao_maxima=1)
    obs = r.AcompanhamentoPesquisa(padrao("roleta", "cor_seg3"), cfg, giros([1, 3, 5]))
    assert obs.pendente is not None
    for evento in giros([2, 1, 3, 5]):
        obs.observar(evento)
    assert obs.saldo == 900 and obs.metricas.entradas == 1
    assert obs.pendente is None and "perda" in obs.motivo


def test_exposicao_considera_todos_alvos_e_protecao():
    obs = r.AcompanhamentoPesquisa(padrao("roleta", "duzia_cob3"), r.ConfigPesquisa(protecao=1), giros([1, 2, 3]))
    assert obs.pendente is None and "Exposição" in obs.motivo  # 21 > 2% de 1.000


def test_pagamento_desconhecido_pausa_observacao():
    cfg = r.ConfigPesquisa(protecao=1)
    obs = r.AcompanhamentoPesquisa(padrao("bacbo", "bb_retomar"), cfg,
                                  [r.RodadaBacBo.do_resultado(x) for x in "PE"])
    assert obs.pendente is not None
    obs.observar(r.RodadaBacBo.do_resultado("E"))
    assert obs.liquidacao_incompleta and obs.pendente is None
    assert obs.metricas.incompletas == 1


@pytest.mark.parametrize("jogo", ["roleta", "bacbo"])
def test_desfazer_restaura_registro_e_observacao(jogo):
    if jogo == "roleta":
        motor = r.MotorWeb(r.Config())
        eventos = giros([1, 3, 5, 2])
        escolhido = padrao(jogo, "cor_inv3")
    else:
        motor = r.MotorBacBo(r.ConfigBacBo())
        eventos = [r.RodadaBacBo.do_resultado(x) for x in "PPPB"]
        escolhido = padrao(jogo, "bb_inv3")
    for evento in eventos[:3]:
        motor.processar(evento.numero if jogo == "roleta" else evento)
    motor.acompanhamento_pesquisa = r.AcompanhamentoPesquisa(escolhido, r.ConfigPesquisa(), list(motor.historico))
    motor.processar(eventos[3].numero if jogo == "roleta" else eventos[3], permitir_desfazer=True)
    assert len(motor.registros_pesquisa) == 4
    assert motor.acompanhamento_pesquisa.metricas.entradas == 1
    assert motor.desfazer()
    assert len(motor.registros_pesquisa) == 3 and motor.acompanhamento_pesquisa.metricas.entradas == 0
    assert not motor.desfazer()


def test_captura_limitada_e_undo_sem_perder_registro_inicial(monkeypatch):
    monkeypatch.setattr(r, "LIMITE_REGISTROS_PESQUISA", 2)
    motor = r.MotorWeb(r.Config())
    motor.processar(1); motor.processar(2)
    motor.processar(3, permitir_desfazer=True)
    assert [x.evento.numero for x in motor.registros_pesquisa] == [2, 3]
    assert motor.descartados_pesquisa == 1
    assert motor.desfazer()
    assert [x.evento.numero for x in motor.registros_pesquisa] == [1, 2]
    assert motor.descartados_pesquisa == 0


def test_historico_inicial_nao_inventa_rodadas_capturadas():
    motor = r.MotorWeb(r.Config())
    motor.carregar_historico([1, 3, 5])
    assert not motor.registros_pesquisa
    motor.processar(2)
    assert len(motor.registros_pesquisa) == 1


def test_sem_registro_no_backtest_legacy():
    motor = r.MotorWeb(r.Config(), registrar=False)
    for n in (1, 1, 1, 1, 2):
        motor.processar(n)
    assert not motor.registros_pesquisa
    assert motor.banca.total().sinais > 0


def test_catalogo_preserva_tres_regras_originais_da_roleta():
    rng, hist = random.Random(47), deque(maxlen=30)
    original = r.EstrategiaRoleta(r.Config())
    mapa = {"cor": "cor_inv4", "duzia": "duzia_cob3", "coluna": "coluna_cob3"}
    for i in range(1000):
        hist.append(r.Giro.a_partir_do_numero(rng.randrange(37)))
        sinais = {s.tipo: s.alvos for s in original.analisar(hist, i)}
        for tipo, chave in mapa.items():
            novo = padrao("roleta", chave).prever(list(hist))
            assert (novo.alvos if novo else None) == sinais.get(tipo)


def test_catalogo_preserva_seis_regras_originais_do_bacbo():
    rng, hist = random.Random(47), []
    mapa = {"rep3": "bb_inv3", "alt4": "bb_alt4", "rep2": "bb_seg2", "emp": "bb_emp", "2x2": "bb_duplas", "surf4": "bb_seg4"}
    for i in range(1000):
        hist.append(rng.choice("PBE")); hist = hist[-30:]
        rodadas = [r.RodadaBacBo.do_resultado(x) for x in hist]
        for original in r.PADROES_BACBO:
            novo = padrao("bacbo", mapa[original.chave]).prever(rodadas)
            assert (novo.alvos[0] if novo else None) == original.detectar(hist)


@pytest.mark.parametrize("valor", [True, 1.5, float("nan"), float("inf")])
def test_dados_bacbo_exigem_inteiros(valor):
    with pytest.raises(ValueError):
        r.RodadaBacBo.dos_dados(valor, 1, 1, 1)
    with pytest.raises(ValueError):
        r.RodadaBacBo.do_resultado("E", valor)


@pytest.mark.parametrize("jogo", ["roleta", "bacbo"])
def test_simulacao_reproduzivel(jogo):
    a, b = r.simular_pesquisa(200, 42, jogo), r.simular_pesquisa(200, 42, jogo)
    assert r.csv_historico_pesquisa(a, jogo) == r.csv_historico_pesquisa(b, jogo)


def test_cli_exporta_relatorio_com_origem_simulada(tmp_path):
    destino = tmp_path/"resultado.json"
    proc = subprocess.run([sys.executable, str(PASTA/"robo_roleta.py"), "--jogo", "bacbo",
                           "--pesquisa-simulada", "300", "--relatorio-pesquisa", str(destino)],
                          capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(destino.read_text())["dados_simulados"]


def test_legacy_sinalizacao_de_saldo_estimado_bacbo():
    banca = r.BancaBacBo(r.ConfigBacBo())
    banca.liquidar(r.SinalBacBo("teste", "teste", "P", 0), r.RodadaBacBo.do_resultado("E"))
    assert banca.liquidacoes_estimadas == 1


def test_calibracao_sincroniza_observacao_e_invalida_undo_antigo():
    motor = r.MotorWeb(r.Config())
    for n in (1, 3, 5):
        motor.processar(n, permitir_desfazer=True)
    motor.acompanhamento_pesquisa = r.AcompanhamentoPesquisa(padrao("roleta", "cor_inv3"), r.ConfigPesquisa(), list(motor.historico))
    assert motor.acompanhamento_pesquisa.pendente is not None
    motor.carregar_historico([2])
    assert motor.acompanhamento_pesquisa.pendente is None
    assert not motor.desfazer()
    assert len(motor.registros_pesquisa) == 3

