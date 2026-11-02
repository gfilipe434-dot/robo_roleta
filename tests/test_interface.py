import sys
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1]/"robo_roleta.py")


@pytest.mark.parametrize("jogo", ["Roleta", "Bac Bo"])
def test_painel_manual_e_laboratorio_simulado(jogo, monkeypatch):
    monkeypatch.delenv("ROBO_ROLETA_LOCAL", raising=False)
    app = AppTest.from_file(APP, default_timeout=40)
    app.session_state["rr_tela"] = "painel"
    app.session_state["rr_jogo_escolhido"] = jogo
    app.session_state["rr_modo"] = "Mesa real (manual)"
    # Descobre o nome do modo a partir do código, mantendo este teste independente
    # de uma mudança de texto dos labels.
    import robo_roleta as r
    app.session_state["rr_modo"] = r.MODO_MANUAL
    app.run()
    assert not app.exception
    area = app.radio(key="rr_area")
    area.set_value("Pesquisa e validação").run()
    assert not app.exception
    prefixo = "pesq_bacbo" if jogo == "Bac Bo" else "pesq_roleta"
    app.radio(key=prefixo+"_fonte").set_value("Simulação de controle").run()
    app.number_input(key=prefixo+"_n").set_value(5000)
    app.button(key=prefixo+"_analisar").click().run()
    assert not app.exception
    rel = app.session_state[prefixo+"_resultado"][0]
    assert rel["dados_simulados"] and not rel["criterios_atendidos_no_historico"]
    assert len(app.dataframe) == 1
    assert rel["selecionado_no_treino"] is not None
    app.button(key=prefixo+"_acompanhar").click().run()
    assert not app.exception
    app.radio(key="rr_area").set_value("Monitor").run()
    assert not app.exception
    # Sessão real guardada atravessa vários reruns; a análise não pode rejeitar
    # essas rodadas porque a classe Python foi redefinida pelo Streamlit.
    sessao = app.session_state["rr_sessao"]
    sessao = sessao.bacbo if jogo == "Bac Bo" else sessao
    for i in range(220):
        sessao.motor.processar(i % 37 if jogo == "Roleta" else r.RodadaBacBo.do_resultado("P" if i % 2 else "B"))
    app.radio(key="rr_area").set_value("Pesquisa e validação").run()
    app.radio(key=prefixo+"_fonte").set_value("Sessão atual").run()
    app.button(key=prefixo+"_analisar").click().run()
    assert not app.exception
    assert not app.error
    assert app.session_state[prefixo+"_resultado"][0]["rodadas"] == 220
