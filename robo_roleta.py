#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
===================================================================================
  ROBÔ DE ANÁLISE DE SINAIS DE ROLETA (Roleta Europeia), execução 100% local
===================================================================================

O QUE ESTE SCRIPT FAZ
  1. Coleta um número novo da roleta (por padrão, de um SIMULADOR fiel à roleta
     europeia: 37 casas, 0 verde, 18 vermelhos e 18 pretos).
  2. Guarda os últimos 20 giros num histórico (collections.deque com maxlen=20).
  3. Analisa o histórico com 3 padrões: repetição de cor, de dúzia e de coluna.
  4. Quando um padrão é ativado, exibe um alerta em destaque com a ação a tomar.
  5. No giro seguinte, valida o sinal sozinho (GREEN ou LOSS), atualiza uma banca
     FICTÍCIA e compara o desempenho com a matemática da roleta.

COMO RODAR (Python 3.9+)
  python robo_roleta.py                        abre um MENU (também funciona com dois cliques)
  python robo_roleta.py --navegador            MESA REAL AUTOMÁTICA: lê a Immersive Roulette
                                               aberta no navegador (precisa: pip install playwright)
  python robo_roleta.py --navegador --url https://site-da-mesa   já abre esse endereço
  python robo_roleta.py --manual               MESA REAL MANUAL: você digita cada número que sai
  python robo_roleta.py --simulador            simulador ao vivo: 1 giro a cada 10 a 15 s
  python robo_roleta.py --rapido               simulador acelerado: 1 giro por segundo
  python robo_roleta.py --giros 50             para sozinho depois de 50 giros
  python robo_roleta.py --backtest 100000      simula 100 mil giros na hora + relatório
  python robo_roleta.py --backtest 100000 --semente 42    backtest reproduzível
  --sem-emoji / --com-emoji                    força o jeito de exibir os emojis
  python robo_roleta.py --web                  PAINEL VISUAL no navegador, rodando escondido
                                               (precisa: pip install streamlit)
  python robo_roleta.py --atalho               cria um atalho na Área de Trabalho para o painel
  python robo_roleta.py --atualizar            baixa a versão mais nova do GitHub e troca este arquivo

  Para parar: Ctrl+C (ou "s" no modo mesa real). O relatório final aparece sempre.

MODOS MESA REAL (Immersive Roulette)
  A Immersive Roulette é uma roleta europeia comum filmada com várias câmeras:
  37 casas, mesmos pagamentos e mesmo RTP (97,3%). Por isso toda a matemática deste
  robô vale para ela sem nenhuma mudança. Nos dois modos o robô analisa, mostra os
  gatilhos e valida tudo numa banca FICTÍCIA. Ele não clica e não aposta nada.
    --navegador  O robô abre uma janela do Chrome com perfil próprio. Você faz login e
                 abre a mesa nela; ele lê sozinho cada número novo da faixa de resultados.
                 Instalação, uma vez só:   pip install playwright
    --manual     Você assiste a mesa e digita cada número. Não precisa de nada instalado.
  Atenção: muitos sites proíbem robôs de leitura nos termos de uso; o risco é de
  bloqueio da conta. Confira as regras do site antes de usar o modo --navegador.

ORGANIZAÇÃO DO CÓDIGO (de cima para baixo)
  1. Config ............... todos os parâmetros ajustáveis
  2. Regras da roleta ..... cores, dúzias, colunas, matemática e exibição de emojis
  3. Modelos de dados ..... Giro, Sinal, ResultadoAposta, EstatisticaPadrao
  4. EstrategiaRoleta ..... os 3 padrões de análise
  5. BancaFicticia ........ liquida as apostas e guarda as estatísticas
  6. Coletores ............ simulador, entrada manual, leitura pelo navegador e
                            modelo de API (AVISO: COLE SEU SCRAPING AQUI)
  7. Painel ............... tudo que é impresso na tela
  8. MonitorRoleta ........ o motor: loop principal que orquestra tudo
  9. main() ............... menu e ponto de partida do programa
"""

from __future__ import annotations

import argparse
import copy
import html
import importlib.util
import json
import os
import queue
import random
import shutil
import socket
import subprocess
import threading
import urllib.request
import webbrowser
import sys
import time
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Deque, Dict, Iterator, List, Optional, Tuple
from urllib.parse import urlparse


# ===================================================================================
# 1) CONFIGURAÇÃO
# -----------------------------------------------------------------------------------
# Tudo o que você talvez queira ajustar fica aqui, num lugar só. Mudou um valor aqui,
# o robô inteiro passa a usar o valor novo; não precisa caçar números no código.
# ===================================================================================
@dataclass
class Config:
    # Tempo (em segundos) entre um giro e outro no simulador
    intervalo_min: float = 10.0
    intervalo_max: float = 15.0

    # Quantos giros o histórico guarda na memória (deque com tamanho máximo)
    tamanho_historico: int = 20

    # Quantas repetições seguidas ativam cada padrão
    gatilho_cor: int = 4      # Padrão 1: 4 cores iguais seguidas
    gatilho_duzia: int = 3    # Padrão 2: 3 números seguidos na mesma dúzia
    gatilho_coluna: int = 3   # Padrão 3: 3 números seguidos na mesma coluna

    # Banca fictícia (nenhum dinheiro real é usado)
    banca_inicial: float = 1000.0
    valor_por_alvo: float = 10.0       # valor em CADA alvo (a cor, cada dúzia, cada coluna)
    protecao_zero: bool = True         # cobrir o 0 junto com cada sinal?
    valor_protecao_zero: float = 1.0   # valor apostado no 0 quando a proteção está ligada

    # Quantas falhas seguidas de coleta o robô tolera antes de desistir
    max_falhas_seguidas: int = 10

    def __post_init__(self) -> None:
        """Valida a configuração logo na criação, para o erro aparecer cedo e claro."""
        if self.intervalo_min < 0 or self.intervalo_max < self.intervalo_min:
            raise ValueError("intervalos inválidos: use 0 <= intervalo_min <= intervalo_max.")
        gatilhos = (self.gatilho_cor, self.gatilho_duzia, self.gatilho_coluna)
        if min(gatilhos) < 2:
            raise ValueError("cada gatilho precisa ser de pelo menos 2 repetições.")
        if self.tamanho_historico <= max(gatilhos):
            raise ValueError("tamanho_historico precisa ser MAIOR que o maior gatilho.")
        if self.valor_por_alvo <= 0 or self.valor_protecao_zero < 0:
            raise ValueError("os valores de aposta precisam ser positivos.")
        if self.max_falhas_seguidas < 1:
            raise ValueError("max_falhas_seguidas precisa ser pelo menos 1.")


# ===================================================================================
# 2) REGRAS FIXAS DA ROLETA EUROPEIA
# -----------------------------------------------------------------------------------
# A roleta europeia tem 37 casas: o 0 (verde) e os números de 1 a 36, sendo 18
# vermelhos e 18 pretos. A lista de vermelhos abaixo é a oficial, igual à de qualquer
# mesa real. Tudo o que não é vermelho (de 1 a 36) é preto.
# ===================================================================================
NUMEROS_VERMELHOS = frozenset({1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36})
NUMEROS_PRETOS = frozenset(range(1, 37)) - NUMEROS_VERMELHOS

VERMELHO, PRETO, VERDE = "VERMELHO", "PRETO", "VERDE"
EMOJI_COR = {VERMELHO: "🔴", PRETO: "⚫", VERDE: "🟢"}
FAIXA_DUZIA = {1: "1 a 12", 2: "13 a 24", 3: "25 a 36"}

# Nomes dos padrões: completos (usados nos alertas) e curtos (usados no placar)
PADROES = {
    "cor": "Padrão 1 — Repetição de Cor",
    "duzia": "Padrão 2 — Repetição de Dúzia",
    "coluna": "Padrão 3 — Repetição de Coluna",
}
NOMES_CURTOS = {"cor": "P1 Cor", "duzia": "P2 Dúzia", "coluna": "P3 Coluna"}

# Matemática de cada tipo de aposta. Serve para comparar "o que aconteceu" com
# "o que a matemática prevê":
#   chance_teorica -> probabilidade real de o alvo sair no próximo giro
#   acerto_minimo  -> taxa de acerto necessária só para EMPATAR (sem a proteção)
#     * Cor paga 1:1: ganha 1 ficha ou perde 1 ficha        -> precisa acertar 50,0%
#     * 2 dúzias / 2 colunas: ganha 1 ficha (2:1 numa, perde
#       a outra) ou perde 2 fichas                           -> precisa acertar 66,7%
MATEMATICA = {
    "cor": {"chance_teorica": 18 / 37, "acerto_minimo": 1 / 2},
    "duzia": {"chance_teorica": 24 / 37, "acerto_minimo": 2 / 3},
    "coluna": {"chance_teorica": 24 / 37, "acerto_minimo": 2 / 3},
}
# Vantagem da casa na roleta europeia: em média, perde-se 1/37 (2,70%) de tudo o
# que é apostado, em QUALQUER tipo de aposta (cor, dúzia, coluna ou número pleno).
VANTAGEM_DA_CASA = 1 / 37


# -----------------------------------------------------------------------------------
# Funções auxiliares de formatação (padrão brasileiro)
# -----------------------------------------------------------------------------------
def formatar_reais(valor: float, com_sinal: bool = False) -> str:
    """Formata dinheiro no padrão BR: 1234.5 -> 'R$ 1.234,50' (ou '+R$ ...' / '-R$ ...')."""
    valor = round(valor, 2) + 0.0  # o "+ 0.0" elimina o "-0.0" que às vezes aparece
    texto = f"{abs(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    if valor < 0:
        return f"-R$ {texto}"
    return f"+R$ {texto}" if com_sinal else f"R$ {texto}"


def formatar_pct(fracao: float) -> str:
    """Formata uma fração como porcentagem BR: 0.4865 -> '48,6%'."""
    return f"{fracao * 100:.1f}%".replace(".", ",")


def formatar_inteiro(valor: int) -> str:
    """Formata inteiro com ponto de milhar: 100000 -> '100.000'."""
    return f"{valor:,}".replace(",", ".")


# -----------------------------------------------------------------------------------
# Emojis com plano B
# -----------------------------------------------------------------------------------
# O console antigo do Windows (a janela que abre quando você dá dois cliques no .py)
# não desenha emojis: eles viram quadradinhos. Nesses casos o robô troca cada emoji
# por um texto curto. Windows Terminal, VS Code, Mac e Linux mostram emoji normalmente.
TEXTO_NO_LUGAR_DO_EMOJI = {
    "🔴": "V:", "⚫": "P:", "🟢": "Z:",
    "🚨": "[!!]", "🎯": ">>", "🔁": "[+]", "📊": "--", "💵": "$$", "⏭️": "->",
    "✅": "[OK]", "❌": "[X]", "🛡️": "[0]", "📈": "##", "🏁": "##", "⚠️": "[!]",
    "⛔": "[X]", "⏳": "...", "⏹️": "[FIM]", "🎰": "", "🧪": "", "↩️": "<-",
    "📝": ">>", "👉": ">", "🌐": "[WEB]", "🔎": ">>",
}
# Alguns emojis carregam um caractere invisível (U+FE0F). Tiramos ele das chaves
# para a troca funcionar com ou sem esse caractere no texto.
TEXTO_NO_LUGAR_DO_EMOJI = {k.replace("️", ""): v for k, v in TEXTO_NO_LUGAR_DO_EMOJI.items()}

USAR_EMOJI = True  # o valor de verdade é decidido no main()
SAIDA_JSON = False  # True quando o robô roda como "leitor" do painel web (seção 10)


def terminal_mostra_emoji() -> bool:
    """Tenta descobrir se o terminal atual consegue desenhar emojis."""
    if os.name != "nt":
        return True  # Mac e Linux: sim
    # No Windows, o Windows Terminal cria a variável WT_SESSION, e o VS Code cria a
    # TERM_PROGRAM. Sem nenhuma das duas, é o console antigo, que não desenha emoji.
    return bool(os.environ.get("WT_SESSION") or os.environ.get("TERM_PROGRAM"))


def adaptar_emojis(texto: str) -> str:
    """Troca os emojis por texto quando o terminal não os desenha (senão, não mexe)."""
    if not USAR_EMOJI:
        texto = texto.replace("️", "")
        for emoji, substituto in TEXTO_NO_LUGAR_DO_EMOJI.items():
            texto = texto.replace(emoji, substituto)
    return texto


def exibir(texto: str = "") -> None:
    """Igual ao print(), mas passando o texto por adaptar_emojis() antes."""
    if SAIDA_JSON:  # no modo leitor do painel, cada mensagem vira uma linha JSON
        if texto.strip():
            print(json.dumps({"tipo": "msg", "texto": texto.strip()}, ensure_ascii=False), flush=True)
        return
    print(adaptar_emojis(texto))


# ===================================================================================
# 3) MODELOS DE DADOS
# -----------------------------------------------------------------------------------
# São "fichas" que carregam informação de um lugar para outro no robô. Usamos
# @dataclass porque ele cria o construtor sozinho e deixa o código bem enxuto.
# ===================================================================================
@dataclass(frozen=True)
class Giro:
    """Um giro da roleta, já classificado (cor, dúzia e coluna)."""

    numero: int
    cor: str
    duzia: Optional[int]    # 1, 2 ou 3 (None quando sai o zero)
    coluna: Optional[int]   # 1, 2 ou 3 (None quando sai o zero)
    horario: datetime

    @classmethod
    def a_partir_do_numero(cls, numero: int, horario: Optional[datetime] = None) -> "Giro":
        """
        Recebe só o número (0 a 36) e descobre o resto sozinho.
        Lança ValueError se o número for inválido, para dado ruim nunca entrar no histórico.
        """
        if isinstance(numero, bool) or not isinstance(numero, int) or not 0 <= numero <= 36:
            raise ValueError(f"número inválido para roleta europeia: {numero!r}")

        if numero == 0:
            cor, duzia, coluna = VERDE, None, None
        else:
            cor = VERMELHO if numero in NUMEROS_VERMELHOS else PRETO
            duzia = (numero - 1) // 12 + 1   # 1–12 -> 1 | 13–24 -> 2 | 25–36 -> 3
            coluna = (numero - 1) % 3 + 1    # 1,4,7... -> 1 | 2,5,8... -> 2 | 3,6,9... -> 3
        return cls(numero, cor, duzia, coluna, horario or datetime.now())

    def rotulo(self) -> str:
        """Representação curta para a tela, ex.: '🔴23'."""
        return f"{EMOJI_COR[self.cor]}{self.numero}"


@dataclass
class Sinal:
    """Uma entrada sugerida pela estratégia, válida apenas para o PRÓXIMO giro."""

    tipo: str            # "cor", "duzia" ou "coluna"
    motivo: str          # o que aconteceu (ex.: "4 VERMELHOS seguidos: ...")
    alvos: Tuple         # onde apostar, ex.: ("PRETO",) ou (2, 3)
    acao: str            # instrução em português para o usuário
    giro_origem: int     # número do giro que disparou o sinal

    @property
    def padrao(self) -> str:
        return PADROES[self.tipo]


@dataclass
class ResultadoAposta:
    """O resultado de um sinal depois que o giro seguinte saiu."""

    sinal: Sinal
    giro: Giro
    status: str            # "GREEN", "GREEN NA PROTEÇÃO", "ZERO (PROTEÇÃO REDUZIU A PERDA)" ou "LOSS"
    total_apostado: float
    lucro: float


@dataclass
class EstatisticaPadrao:
    """Placar acumulado de um padrão (ou de todos somados)."""

    sinais: int = 0
    greens: int = 0            # acertos da aposta principal
    greens_protecao: int = 0   # saiu o 0 e a proteção deu lucro
    losses: int = 0
    apostado: float = 0.0
    lucro: float = 0.0

    @property
    def taxa_acerto(self) -> float:
        """Fração de sinais em que a aposta PRINCIPAL acertou."""
        return self.greens / self.sinais if self.sinais else 0.0


# ===================================================================================
# 4) ESTRATÉGIAS DE ANÁLISE
# -----------------------------------------------------------------------------------
# Esta classe só "olha" o histórico e decide se existe sinal. Ela não imprime na
# tela, não mexe na banca e não sabe de onde vêm os números. Essa separação deixa
# cada peça fácil de testar e de trocar.
#
# Para criar um padrão novo: escreva um método que receba (historico, numero_giro)
# e devolva um Sinal ou None, e acrescente-o na tupla self._padroes.
# ===================================================================================
class EstrategiaRoleta:
    def __init__(self, config: Config) -> None:
        self.config = config
        # Lista de padrões que serão testados a cada giro, nesta ordem
        self._padroes = (
            self.padrao_repeticao_cor,
            self.padrao_repeticao_duzia,
            self.padrao_repeticao_coluna,
        )

    # -------------------------------------------------------------------------------
    # Ponto de entrada: roda todos os padrões e devolve os sinais encontrados
    # -------------------------------------------------------------------------------
    def analisar(self, historico: Deque[Giro], numero_giro: int) -> List[Sinal]:
        sinais: List[Sinal] = []
        for padrao in self._padroes:
            try:
                sinal = padrao(historico, numero_giro)
            except Exception as erro:  # um padrão com defeito não derruba os outros
                exibir(f"⚠️  Erro em {padrao.__name__}: {erro} (os demais padrões seguem normalmente)")
                continue
            if sinal is not None:
                sinais.append(sinal)
        return sinais

    # -------------------------------------------------------------------------------
    # Ferramenta matemática comum: tamanho da sequência no final do histórico
    # -------------------------------------------------------------------------------
    @staticmethod
    def contar_sequencia_final(valores: List[Optional[object]]) -> int:
        """
        Conta quantos valores IGUAIS aparecem seguidos no FINAL da lista.
            ["PRETO", "VERMELHO", "VERMELHO", "VERMELHO"] -> 3
        None representa o zero: ele "quebra" qualquer sequência.
        """
        if not valores or valores[-1] is None:
            return 0
        alvo = valores[-1]
        contagem = 0
        for valor in reversed(valores):  # anda de trás para frente
            if valor != alvo:
                break
            contagem += 1
        return contagem

    @staticmethod
    def _listar(giros: List[Giro]) -> str:
        """Lista giros do mais antigo para o mais novo, ex.: '🔴5 🔴14 🔴23'."""
        return " ".join(g.rotulo() for g in giros)

    # -------------------------------------------------------------------------------
    # PADRÃO 1: Repetição de Cor
    # 4 vermelhos seguidos -> apostar no preto | 4 pretos seguidos -> apostar no vermelho
    # -------------------------------------------------------------------------------
    def padrao_repeticao_cor(self, historico: Deque[Giro], numero_giro: int) -> Optional[Sinal]:
        n = self.config.gatilho_cor
        cores = [None if g.cor == VERDE else g.cor for g in historico]

        # Dispara só quando a sequência atinge EXATAMENTE n. Se ela continuar
        # (5, 6, 7 iguais...), não dispara de novo: cada sequência gera uma entrada só.
        if self.contar_sequencia_final(cores) != n:
            return None

        cor_repetida = cores[-1]
        cor_alvo = PRETO if cor_repetida == VERMELHO else VERMELHO
        return Sinal(
            tipo="cor",
            motivo=f"{n} {cor_repetida}S seguidos: {self._listar(list(historico)[-n:])}",
            alvos=(cor_alvo,),
            acao=f"Apostar no {EMOJI_COR[cor_alvo]} {cor_alvo}",
            giro_origem=numero_giro,
        )

    # -------------------------------------------------------------------------------
    # PADRÃO 2: Repetição de Dúzia
    # 3 números seguidos na mesma dúzia -> cobrir as outras duas dúzias
    # -------------------------------------------------------------------------------
    def padrao_repeticao_duzia(self, historico: Deque[Giro], numero_giro: int) -> Optional[Sinal]:
        return self._padrao_repeticao_terco(historico, numero_giro, "duzia", self.config.gatilho_duzia)

    # -------------------------------------------------------------------------------
    # PADRÃO 3: Repetição de Coluna
    # 3 números seguidos na mesma coluna -> cobrir as outras duas colunas
    # -------------------------------------------------------------------------------
    def padrao_repeticao_coluna(self, historico: Deque[Giro], numero_giro: int) -> Optional[Sinal]:
        return self._padrao_repeticao_terco(historico, numero_giro, "coluna", self.config.gatilho_coluna)

    def _padrao_repeticao_terco(self, historico: Deque[Giro], numero_giro: int,
                                tipo: str, n: int) -> Optional[Sinal]:
        """
        Lógica compartilhada por Dúzia e Coluna: as duas dividem a mesa em 3 grupos
        de 12 números, então a regra é idêntica e só muda o atributo lido do giro.
        """
        valores = [g.duzia if tipo == "duzia" else g.coluna for g in historico]
        if self.contar_sequencia_final(valores) != n:
            return None

        repetido = valores[-1]
        alvos = tuple(grupo for grupo in (1, 2, 3) if grupo != repetido)  # os outros dois grupos
        ultimos = self._listar(list(historico)[-n:])

        if tipo == "duzia":
            motivo = f"{n} números seguidos na {repetido}ª Dúzia ({FAIXA_DUZIA[repetido]}): {ultimos}"
            acao = (f"Cobrir a {alvos[0]}ª Dúzia ({FAIXA_DUZIA[alvos[0]]}) "
                    f"e a {alvos[1]}ª Dúzia ({FAIXA_DUZIA[alvos[1]]})")
        else:
            motivo = f"{n} números seguidos na Coluna {repetido}: {ultimos}"
            acao = f"Cobrir a Coluna {alvos[0]} e a Coluna {alvos[1]}"

        return Sinal(tipo=tipo, motivo=motivo, alvos=alvos, acao=acao, giro_origem=numero_giro)


# ===================================================================================
# 5) BANCA FICTÍCIA
# -----------------------------------------------------------------------------------
# Liquida cada sinal com as regras de pagamento reais da roleta europeia e guarda
# o placar de cada padrão. Nenhum dinheiro de verdade é envolvido.
#
# Pagamentos usados (o valor recebido inclui a ficha apostada de volta):
#   Cor ............ paga 1:1  -> acertou, recebe 2x a ficha
#   Dúzia/Coluna ... paga 2:1  -> acertou, recebe 3x a ficha
#   Número pleno ... paga 35:1 -> acertou, recebe 36x a ficha (usado na proteção do 0)
#   Saiu o 0 ....... aposta em cor, dúzia e coluna PERDE (roleta europeia, sem "la partage")
# ===================================================================================
class BancaFicticia:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.saldo: float = config.banca_inicial
        self.menor_saldo: float = config.banca_inicial
        self.quebrou_no_giro: Optional[int] = None
        self.estatisticas: Dict[str, EstatisticaPadrao] = {tipo: EstatisticaPadrao() for tipo in PADROES}

    def liquidar(self, sinal: Sinal, giro: Giro, numero_giro: int) -> ResultadoAposta:
        """Confere o sinal contra o giro que acabou de sair e atualiza saldo e placar."""
        ficha = self.config.valor_por_alvo
        protecao = self.config.valor_protecao_zero if self.config.protecao_zero else 0.0

        # --- Aposta principal ------------------------------------------------------
        if sinal.tipo == "cor":
            acertou = giro.cor in sinal.alvos
            retorno = ficha * 2 if acertou else 0.0
        elif sinal.tipo in ("duzia", "coluna"):
            sorteado = giro.duzia if sinal.tipo == "duzia" else giro.coluna  # None se saiu o 0
            acertou = sorteado in sinal.alvos
            retorno = ficha * 3 if acertou else 0.0
        else:
            raise ValueError(f"tipo de sinal desconhecido: {sinal.tipo}")

        # --- Proteção no zero ------------------------------------------------------
        saiu_zero = giro.numero == 0
        if saiu_zero and protecao > 0:
            retorno += protecao * 36

        total_apostado = ficha * len(sinal.alvos) + protecao
        lucro = retorno - total_apostado

        # --- Classificação do resultado --------------------------------------------
        if acertou:
            status = "GREEN"
        elif saiu_zero and protecao > 0:
            status = "GREEN NA PROTEÇÃO" if lucro > 0 else "ZERO (PROTEÇÃO REDUZIU A PERDA)"
        else:
            status = "LOSS"

        # --- Atualiza placar do padrão e saldo -------------------------------------
        est = self.estatisticas[sinal.tipo]
        est.sinais += 1
        est.apostado += total_apostado
        est.lucro += lucro
        if status == "GREEN":
            est.greens += 1
        elif status == "GREEN NA PROTEÇÃO":
            est.greens_protecao += 1
        else:
            est.losses += 1

        self.saldo += lucro
        self.menor_saldo = min(self.menor_saldo, self.saldo)
        if self.saldo <= 0 and self.quebrou_no_giro is None:
            self.quebrou_no_giro = numero_giro

        return ResultadoAposta(sinal, giro, status, total_apostado, lucro)

    def total(self) -> EstatisticaPadrao:
        """Soma o placar de todos os padrões."""
        soma = EstatisticaPadrao()
        for est in self.estatisticas.values():
            soma.sinais += est.sinais
            soma.greens += est.greens
            soma.greens_protecao += est.greens_protecao
            soma.losses += est.losses
            soma.apostado += est.apostado
            soma.lucro += est.lucro
        return soma


# ===================================================================================
# 6) COLETORES DE DADOS
# -----------------------------------------------------------------------------------
# Coletor = a peça que traz o próximo número da roleta. O MonitorRoleta não sabe se
# o número veio de um simulador, de uma API ou de um WebSocket: ele só chama
# obter_proximo_numero(). Por isso dá para trocar a fonte sem mexer no resto.
# ===================================================================================
class ColetorBase(ABC):
    """Molde (classe abstrata) que todo coletor precisa seguir."""

    descricao: str = "coletor genérico"
    permite_desfazer: bool = False  # só o modo manual permite apagar o último número

    @abstractmethod
    def obter_proximo_numero(self) -> int:
        """Espera até existir um giro NOVO e devolve o número sorteado (0 a 36)."""

    def ler_historico_inicial(self) -> List[int]:
        """
        Números que já tinham saído antes de o robô ligar, do mais antigo para o mais
        novo. Por padrão não há nenhum; os modos de mesa real sobrescrevem este método.
        """
        return []

    def fechar(self) -> None:
        """Libera recursos no fim (ex.: fecha o navegador). Por padrão não faz nada."""


# -----------------------------------------------------------------------------------
# Comandos que o usuário digita no modo manual. Não são erros: são "recados" que o
# coletor manda para o MonitorRoleta usando exceções próprias.
# -----------------------------------------------------------------------------------
class ComandoUsuario(Exception):
    """Base dos comandos digitados no modo manual."""


class PedidoDesfazer(ComandoUsuario):
    """O usuário digitou 'd': apagar o último número (para corrigir erro de digitação)."""


class PedidoEncerrar(ComandoUsuario):
    """O usuário digitou 's' (ou fechou a entrada): encerrar e mostrar o relatório."""


# ###################################################################################
# ###################################################################################
# ##                                                                               ##
# ##          ⚠️ ⚠️ ⚠️    AVISO: COLE SEU SCRAPING AQUI    ⚠️ ⚠️ ⚠️                ##
# ##                                                                               ##
# ###################################################################################
# ###################################################################################
#
# PARA A IMMERSIVE ROULETTE ISSO JÁ ESTÁ PRONTO: é o ColetorNavegador, mais abaixo
# (opção 1 do menu, ou --navegador). Este bloco serve para outras mesas e sites.
#
# O robô pega os números de um "coletor". Para ler uma mesa nova, você cria um
# coletor que busque os números de verdade. O resto do robô (padrões, alertas,
# banca e validação) NÃO muda em nada.
#
# -----------------------------------------------------------------------------------
# A ÚNICA REGRA (o "contrato" que qualquer coletor precisa cumprir)
# -----------------------------------------------------------------------------------
#   - Herdar de ColetorBase e ter o método  obter_proximo_numero(self) -> int
#   - Esse método deve ESPERAR até sair um giro NOVO e devolver o número (0 a 36).
#   - Nunca devolver o mesmo giro duas vezes (senão o robô enxerga repetição falsa
#     e dispara sinais errados).
#   - Se algo der errado (internet caiu, site mudou o formato), basta lançar uma
#     exceção: o MonitorRoleta já trata, espera e tenta de novo sozinho.
#
# -----------------------------------------------------------------------------------
# OPÇÃO A: API que devolve JSON (via requests)   >>> já pronta: classe ColetorAPI <<<
# -----------------------------------------------------------------------------------
#   1. Instale a biblioteca:   pip install requests
#   2. Descubra a URL: abra a página da mesa no navegador, aperte F12, vá na aba
#      "Rede" (Network), filtre por "Fetch/XHR" e espere um giro. Procure a
#      requisição que traz o histórico de números. Clique nela e copie:
#        - a URL (aba "Cabeçalhos"/"Headers")
#        - o formato do JSON (aba "Resposta"/"Response")
#   3. Ajuste o método _extrair_id_e_numero() da ColetorAPI para o formato do seu
#      JSON (é o ÚNICO trecho que depende do site).
#   4. Lá embaixo, na função main(), troque:
#          coletor = ColetorSimulado(...)
#      por:
#          coletor = ColetorAPI(url="https://SEU-ENDPOINT-AQUI", intervalo_consulta=2.0)
#
# -----------------------------------------------------------------------------------
# OPÇÃO B: WebSocket (quando o site "empurra" o resultado em tempo real)
# -----------------------------------------------------------------------------------
#   Na aba "Rede" do F12, filtre por "WS". Se aparecer uma conexão ali, os
#   resultados chegam por ela. Esqueleto pronto para adaptar
#   (pip install websocket-client):
#
#       import json, queue, threading
#       import websocket
#
#       class ColetorWebSocket(ColetorBase):
#           descricao = "WebSocket ao vivo"
#
#           def __init__(self, url: str) -> None:
#               self.fila: queue.Queue = queue.Queue()   # guarda os números que chegam
#               self.ws = websocket.WebSocketApp(url, on_message=self._ao_receber)
#               # roda a conexão numa thread separada, sem travar o robô
#               threading.Thread(target=self.ws.run_forever, daemon=True).start()
#
#           def _ao_receber(self, ws, mensagem: str) -> None:
#               dados = json.loads(mensagem)              # ADAPTE ao formato real
#               if dados.get("tipo") == "resultado":      # ADAPTE: filtre só resultados
#                   self.fila.put(int(dados["numero"]))
#
#           def obter_proximo_numero(self) -> int:
#               # espera até 2 minutos por um giro novo; se não vier, lança
#               # queue.Empty e o MonitorRoleta tenta de novo
#               return self.fila.get(timeout=120)
#
#   Depois, no main():  coletor = ColetorWebSocket(url="wss://SEU-ENDPOINT-AQUI")
#
# Observação: confira os termos de uso do site antes de automatizar a leitura.
# ###################################################################################


class ColetorSimulado(ColetorBase):
    """
    Simula uma roleta europeia: cada um dos 37 números (0 a 36) tem exatamente a
    mesma chance (1/37) a cada giro, e um giro não depende do anterior. É assim
    que funcionam a roda física bem calibrada e o gerador certificado das mesas online.
    """

    descricao = "Simulador local de roleta europeia"

    def __init__(self, intervalo_min: float, intervalo_max: float, semente: Optional[int] = None) -> None:
        self.intervalo_min = intervalo_min
        self.intervalo_max = intervalo_max
        # Gerador próprio: com a mesma semente, a sequência de números se repete
        # (útil para comparar ajustes de estratégia no backtest)
        self._rng = random.Random(semente)

    def obter_proximo_numero(self) -> int:
        # Espera o "tempo de giro" da mesa (no backtest o intervalo é 0, sem espera)
        if self.intervalo_max > 0:
            time.sleep(self._rng.uniform(self.intervalo_min, self.intervalo_max))
        return self._rng.randint(0, 36)  # 0 a 36, todos com a mesma probabilidade


def ler_teclado(mensagem: str) -> str:
    """Lê uma linha do teclado, já limpa e em minúsculas."""
    try:
        return input(adaptar_emojis(mensagem)).strip().lower()
    except EOFError:  # Ctrl+Z (Windows) ou Ctrl+D (Mac/Linux) também encerram
        raise PedidoEncerrar() from None


class ColetorManual(ColetorBase):
    """
    MODO MESA REAL: você assiste a mesa (ex.: Immersive Roulette) e digita o número
    que saiu. O robô analisa, avisa os gatilhos e valida numa banca fictícia, sem
    apostar nada. Não depende de site, login nem internet.

    Comandos aceitos:
        0 a 36 -> registra o número que saiu
        d      -> desfaz o último número (corrige erro de digitação)
        s      -> encerra e mostra o relatório final
    """

    permite_desfazer = True

    def __init__(self, nome_mesa: str = "Immersive Roulette") -> None:
        self.nome_mesa = nome_mesa
        self.descricao = f"Entrada manual — {nome_mesa}"

    @staticmethod
    def _ler(mensagem: str) -> str:
        return ler_teclado(mensagem)

    def ler_historico_inicial(self) -> List[int]:
        """
        Pergunta, uma vez só, os últimos números que a mesa já mostra na tela, para o
        robô começar com contexto em vez de esperar vários giros.
        """
        exibir("📝 Quer carregar os últimos números que a mesa já mostra?")
        exibir("   Digite do MAIS RECENTE para o mais antigo, separados por espaço")
        exibir("   (ex.: 17 4 32 0 21). Ou só aperte Enter para começar do zero.")
        while True:
            texto = self._ler("   Histórico: ")
            if texto in ("s", "sair"):
                raise PedidoEncerrar()
            if not texto:
                return []
            try:
                numeros = [int(parte) for parte in texto.replace(",", " ").split()]
                if any(not 0 <= n <= 36 for n in numeros):
                    raise ValueError("fora de 0 a 36")
            except ValueError:
                exibir("   ⚠️  Use só números de 0 a 36 separados por espaço. Tente de novo.")
                continue
            # Você digitou do mais recente para o mais antigo; o robô guarda ao contrário
            return list(reversed(numeros))

    def obter_proximo_numero(self) -> int:
        while True:  # fica perguntando até receber algo válido
            texto = self._ler("👉 Número que saiu (0-36) | d = desfazer | s = sair: ")
            if texto in ("s", "sair"):
                raise PedidoEncerrar()
            if texto in ("d", "desfazer"):
                raise PedidoDesfazer()
            if texto.isdigit() and 0 <= int(texto) <= 36:
                return int(texto)
            exibir("   ⚠️  Entrada inválida: digite um número de 0 a 36, 'd' ou 's'.")


# -----------------------------------------------------------------------------------
# JavaScript que roda DENTRO da página da mesa a cada leitura.
# A Evolution marca cada número da faixa de últimos resultados assim:
#     <div data-role="number-22" class="..."><span>22</span></div>
# O script:
#   1. acha todos esses elementos visíveis (inclusive dentro de componentes isolados,
#      o chamado "shadow DOM");
#   2. para cada um, sobe pelos "pais" até achar o menor bloco que reúne 3 ou mais
#      números: esse bloco é uma faixa candidata (funciona mesmo se cada número
#      estiver dentro de uma caixinha própria);
#   3. devolve cada faixa como uma lista de números, na ordem em que aparecem na tela,
#      junto com contagens usadas no diagnóstico.
# As classes (ex.: "s3jQ_u") são nomes embaralhados que mudam com atualizações; por
# isso o robô se guia pelo data-role, que é um nome legível e estável.
# -----------------------------------------------------------------------------------
JS_LER_FAIXAS = r"""
() => {
    const SELETOR = '[data-role^="number-"]';
    const numeroDe = el => {
        const achado = /^number-(\d{1,2})$/.exec(el.getAttribute('data-role') || '');
        return achado && parseInt(achado[1], 10) <= 36 ? parseInt(achado[1], 10) : null;
    };
    const visivel = el => el.getClientRects().length > 0;

    // Todas as "raízes" da página: o documento e os shadow DOMs abertos dentro dele
    const raizes = [document];
    for (let i = 0; i < raizes.length; i++) {
        for (const el of raizes[i].querySelectorAll('*')) {
            if (el.shadowRoot) raizes.push(el.shadowRoot);
        }
    }

    let total = 0, visiveis = 0;
    const blocos = new Set();
    for (const raiz of raizes) {
        for (const el of raiz.querySelectorAll(SELETOR)) {
            if (numeroDe(el) === null) continue;
            total++;
            if (!visivel(el)) continue;
            visiveis++;
            let bloco = el.parentElement;  // sobe até o menor bloco com 3+ números
            while (bloco && bloco.querySelectorAll(SELETOR).length < 3) bloco = bloco.parentElement;
            if (bloco) blocos.add(bloco);
        }
    }
    // Se um bloco contém outro, fica só o de dentro (o mais específico)
    const finais = [...blocos].filter(b => ![...blocos].some(o => o !== b && b.contains(o)));

    const grupos = finais.map(bloco => {
        const numeros = [];
        for (const el of bloco.querySelectorAll(SELETOR)) {
            const n = numeroDe(el);
            if (n !== null && visivel(el)) numeros.push(n);
        }
        const classe = typeof bloco.className === 'string' ? bloco.className : '';
        return {chave: bloco.tagName + '|' + (bloco.getAttribute('data-role') || '') + '|' + classe,
                numeros: numeros};
    });
    return {total: total, visiveis: visiveis, grupos: grupos};
}
"""


class ColetorNavegador(ColetorBase):
    """
    MODO MESA REAL AUTOMÁTICO: o robô abre uma janela NORMAL do Google Chrome, com um
    perfil só dele, e liga a "porta de depuração" do Chrome (o recurso oficial que as
    ferramentas de desenvolvedor usam para ler uma página). Você faz login e abre a
    Immersive Roulette nessa janela; daí em diante ele lê sozinho a faixa de últimos
    resultados da mesa, uma vez por segundo. Ele só LÊ: não clica, não aposta e não vê
    sua senha (o login é você quem faz, na janela).

    Quando o robô termina, a janela do Chrome continua aberta. Na próxima vez ele se
    conecta nela de novo, sem precisar abrir outra nem refazer login.

    Como ele acha a faixa: procura os elementos  data-role="number-N"  em todas as abas
    e em todos os iframes (o jogo da Evolution roda dentro de um iframe do cassino).

    Como ele percebe um número novo: compara a faixa atual com a anterior. Se antes era
    [22, 1, 25, ...] e agora é [7, 22, 1, 25, ...], saiu o 7. Funciona com número repetido
    (22 seguido de 22) e recupera giros perdidos se uma leitura atrasar.

    Precisa de:  pip install playwright   (usa o Chrome que você já tem instalado)
    """

    NOME_MESA = "Immersive Roulette"
    INTERVALO_LEITURA = 1.0  # segundos entre uma leitura e outra
    EMENDA_MINIMA = 3        # quantos números em comum confirmam onde as leituras se emendam
    TOLERANCIA_SUMICO = 15   # segundos sem achar a faixa antes de procurar de novo
    PORTA_DEPURACAO = 9222   # porta local (só no seu PC) por onde o robô lê o Chrome
    # Opções oficiais do Chrome que impedem que ele "durma" quando está minimizado ou
    # fora da tela (sem elas, uma página escondida para de se atualizar).
    OPCOES_SEMPRE = ["--disable-background-timer-throttling", "--disable-backgrounding-occluded-windows",
                     "--disable-renderer-backgrounding"]
    # Modo escondido: a janela abre fora da área da tela, então você não a vê, e sem som
    # (a transmissão da mesa tem áudio, e escondida não haveria como silenciar).
    OPCOES_ESCONDIDO = ["--window-position=-2400,-2400", "--window-size=1280,860", "--mute-audio"]
    # Modo com janela: posição explícita na tela. Sem isso o Chrome reabriria onde estava da
    # última vez, ou seja, escondido, se a vez anterior foi no modo escondido.
    OPCOES_JANELA = ["--window-position=40,40", "--window-size=1280,860"]

    def __init__(self, url: Optional[str] = None, pasta_perfil: Optional[str] = None,
                 headless: bool = False, escondido: bool = False) -> None:
        self.escondido = escondido
        try:
            from playwright.sync_api import Error as ErroPlaywright, sync_playwright
        except ImportError as erro:
            raise RuntimeError("biblioteca 'playwright' não instalada. Rode: pip install playwright") from erro

        self._ErroPlaywright = ErroPlaywright
        self.descricao = "Navegador — leitura automática da mesa"

        # Perfil próprio do robô, numa pasta ao lado deste arquivo. O login que você
        # fizer nele fica salvo para as próximas vezes, sem mexer no seu Chrome normal.
        if pasta_perfil is None:
            pasta_perfil = os.path.join(os.path.dirname(os.path.abspath(__file__)), "perfil_navegador_robo")

        self._pw = sync_playwright().start()
        self._navegador = None
        try:
            if headless:
                # Só para testes automáticos: o Playwright abre um navegador invisível.
                self._contexto = self._pw.chromium.launch_persistent_context(pasta_perfil, headless=True)
            else:
                self._navegador = self._conectar_no_chrome(pasta_perfil, escondido)
                contextos = self._navegador.contexts
                self._contexto = contextos[0] if contextos else self._navegador.new_context()
        except Exception:
            self._pw.stop()
            raise

        pagina = self._contexto.pages[0] if self._contexto.pages else self._contexto.new_page()
        if url:
            try:
                pagina.goto(url)
            except ErroPlaywright as erro:
                exibir(f"⚠️  Não consegui abrir {url} ({str(erro).splitlines()[0]}). "
                       f"Digite o endereço direto na janela do navegador.")

        # Estado da leitura
        self._host: Optional[str] = None       # site do iframe onde a faixa está
        self._chave: Optional[str] = None      # "impressão digital" da faixa escolhida
        self._invertida = False                # True se a faixa vier do mais antigo para o mais novo
        self._ultima: List[int] = []           # última leitura confirmada (mais recente primeiro)
        self._pendente: Optional[List[int]] = None  # leitura nova esperando confirmação
        self._fila: Deque[int] = deque()       # números novos ainda não entregues ao motor
        self._sumiu_desde: Optional[float] = None
        self._avisou_sumico = False

    def _conectar_no_chrome(self, pasta_perfil: str, escondido: bool = False):
        """Conecta no Chrome do robô; se ele não estiver aberto (ou estiver no outro modo), abre."""
        endereco = f"http://127.0.0.1:{self.PORTA_DEPURACAO}"
        modo = "escondido" if escondido else "janela"
        marcador = os.path.join(pasta_perfil, "modo_do_robo.txt")  # em que modo o Chrome foi aberto

        # 1) O Chrome do robô ficou aberto de uma execução anterior? Se for no mesmo modo, só conecta.
        try:
            navegador = self._pw.chromium.connect_over_cdp(endereco, timeout=3000)
        except self._ErroPlaywright:
            navegador = None
        if navegador is not None:
            try:
                with open(marcador, encoding="utf-8") as arq:
                    modo_atual = arq.read().strip()
            except OSError:
                modo_atual = "janela"
            if modo_atual == modo:
                return navegador
            # Está no outro modo: fecha e reabre (o login continua salvo no perfil)
            exibir(f"🌐 Reabrindo o Chrome do robô {'escondido' if escondido else 'com janela'}...")
            self._fechar_chrome_de_verdade(navegador)
            prazo = time.time() + 15
            while time.time() < prazo:  # espera o Chrome antigo terminar de fechar
                time.sleep(0.5)
                try:
                    self._pw.chromium.connect_over_cdp(endereco, timeout=1000).close()
                except self._ErroPlaywright:
                    break

        # 2) Abre um Chrome comum (igual a clicar no ícone), com perfil próprio e a porta de
        #    depuração ligada. A porta só aceita conexões do seu próprio PC.
        executavel = self._achar_chrome()
        if executavel is None:
            raise RuntimeError("não encontrei o Google Chrome instalado neste computador.")
        comando = [executavel, f"--remote-debugging-port={self.PORTA_DEPURACAO}",
                   f"--user-data-dir={pasta_perfil}", "--no-first-run", "--no-default-browser-check"]
        comando += self.OPCOES_SEMPRE + (self.OPCOES_ESCONDIDO if escondido else self.OPCOES_JANELA)
        subprocess.Popen(comando, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            os.makedirs(pasta_perfil, exist_ok=True)
            with open(marcador, "w", encoding="utf-8") as arq:
                arq.write(modo)
        except OSError:
            pass

        prazo = time.time() + 30  # o Chrome pode demorar alguns segundos para abrir
        while time.time() < prazo:
            time.sleep(0.5)
            try:
                return self._pw.chromium.connect_over_cdp(endereco, timeout=3000)
            except self._ErroPlaywright:
                continue
        raise RuntimeError("abri o Chrome, mas não consegui me conectar a ele. Feche todas as "
                           "janelas do Chrome do robô e tente de novo.")

    @staticmethod
    def _achar_chrome() -> Optional[str]:
        """Procura o executável do Google Chrome nos lugares de costume."""
        candidatos = []
        if os.name == "nt":  # Windows
            for variavel in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
                base = os.environ.get(variavel)
                if base:
                    candidatos.append(os.path.join(base, "Google", "Chrome", "Application", "chrome.exe"))
        elif sys.platform == "darwin":  # Mac
            candidatos.append("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        for nome in ("google-chrome", "google-chrome-stable", "chrome", "chromium", "chromium-browser"):
            achado = shutil.which(nome)
            if achado:
                candidatos.append(achado)
        return next((c for c in candidatos if os.path.isfile(c)), None)

    # -------------------------------------------------------------------------------
    # Leitura da página
    # -------------------------------------------------------------------------------
    def _ler_grupos(self, so_do_host: Optional[str] = None,
                    diagnostico: Optional[List[str]] = None) -> List[Tuple[str, str, List[int]]]:
        """
        Lê as faixas candidatas em todas as abas e iframes: (site, chave, números).
        Se receber a lista 'diagnostico', anota nela o que viu em cada frame.
        """
        desconectado = self._navegador is not None and not self._navegador.is_connected()
        paginas = [] if desconectado else self._contexto.pages
        if not paginas:
            exibir("\n🌐 O navegador foi fechado.")
            raise PedidoEncerrar()

        grupos: List[Tuple[str, str, List[int]]] = []
        vistos = set()
        for n_aba, pagina in enumerate(paginas, start=1):
            for frame in pagina.frames:
                host = urlparse(frame.url).netloc
                if so_do_host is not None and host != so_do_host:
                    continue
                try:
                    leitura = frame.evaluate(JS_LER_FAIXAS)
                except self._ErroPlaywright as erro:
                    if diagnostico is not None and host:
                        diagnostico.append(f"aba {n_aba} | {host}: não consegui ler "
                                           f"({str(erro).splitlines()[0][:70]})")
                    continue  # frame carregando, recarregando ou fechado: tenta na próxima
                if diagnostico is not None and (leitura["total"] or not diagnostico):
                    tamanhos = [len(g["numeros"]) for g in leitura["grupos"]]
                    diagnostico.append(f"aba {n_aba} | {host or '(vazio)'}: {leitura['total']} números "
                                       f"no código, {leitura['visiveis']} visíveis, blocos {tamanhos}")
                for item in leitura["grupos"]:
                    numeros = item["numeros"]
                    # Descarta grupos pequenos demais e a grade de apostas (que tem os 37 números)
                    if len(numeros) < self.EMENDA_MINIMA or len(set(numeros)) >= 30:
                        continue
                    if (host, item["chave"]) in vistos:
                        continue  # mesma faixa repetida na página (ex.: layout duplicado)
                    vistos.add((host, item["chave"]))
                    grupos.append((host, item["chave"], numeros))
        return grupos

    def _ler_faixa_escolhida(self) -> Optional[List[int]]:
        """Lê só a faixa confirmada na calibração, já na ordem 'mais recente primeiro'."""
        for _host, chave, numeros in self._ler_grupos(so_do_host=self._host):
            if chave == self._chave:
                return list(reversed(numeros)) if self._invertida else numeros
        return None

    # -------------------------------------------------------------------------------
    # Calibração: acha a faixa e pede para você confirmar
    # -------------------------------------------------------------------------------
    def ler_historico_inicial(self) -> List[int]:
        exibir("🌐 Na janela do Chrome que o robô abriu:")
        exibir("   1) entre no site e faça login (só na primeira vez; o login fica salvo)")
        exibir("   2) abra a Immersive Roulette e deixe a mesa aparecendo na tela")
        exibir("   O robô acha a faixa de resultados sozinho.\n")
        while True:
            host, chave, numeros = self._esperar_e_escolher_faixa()
            invertida = False
            while True:
                faixa = list(reversed(numeros)) if invertida else numeros
                exibir("🔎 Faixa encontrada (o PRIMEIRO deve ser o último número que saiu):")
                exibir("   " + " ".join(Giro.a_partir_do_numero(n).rotulo() for n in faixa[:15]))
                resposta = ler_teclado("   Confere com a mesa? Enter = sim | i = está invertida | "
                                       "n = procurar de novo | sair: ")
                if resposta == "":
                    self._host, self._chave, self._invertida, self._ultima = host, chave, invertida, faixa
                    exibir("✅ Leitura automática ligada. Agora é só deixar a mesa aberta no navegador.")
                    return list(reversed(faixa))  # o motor quer do mais antigo para o mais novo
                if resposta == "i":
                    invertida = not invertida
                elif resposta == "n":
                    break
                elif resposta == "sair":
                    raise PedidoEncerrar()
                else:
                    exibir("   ⚠️  Responda com Enter, i, n ou sair.")

    def _esperar_e_escolher_faixa(self) -> Tuple[str, str, List[int]]:
        """Espera a mesa aparecer; se houver mais de uma faixa candidata, pergunta qual é."""
        ultimo_aviso = time.time()
        avisos = 0
        while True:
            grupos = self._ler_grupos()
            if grupos:
                break
            if time.time() - ultimo_aviso > 20:
                avisos += 1
                exibir("⏳ Procurando a faixa de resultados... (abra a Immersive Roulette no navegador)")
                if avisos >= 2:  # a partir de ~40 s, mostra o que está enxergando na página
                    self._exibir_diagnostico()
                ultimo_aviso = time.time()
            time.sleep(self.INTERVALO_LEITURA)

        if len(grupos) == 1:
            return grupos[0]
        exibir(f"🔎 Achei {len(grupos)} faixas de números na página:")
        for i, (_host, _chave, numeros) in enumerate(grupos, start=1):
            exibir(f"   {i}) " + " ".join(str(n) for n in numeros[:15]))
        while True:
            resposta = ler_teclado("   Qual delas é a faixa de últimos resultados da mesa? ")
            if resposta.isdigit() and 1 <= int(resposta) <= len(grupos):
                return grupos[int(resposta) - 1]
            exibir("   ⚠️  Digite um dos números da lista.")

    def _exibir_diagnostico(self) -> None:
        """Mostra, frame por frame, quantos números o robô enxerga (para achar problemas)."""
        linhas: List[str] = []
        self._ler_grupos(diagnostico=linhas)
        total_frames = sum(len(p.frames) for p in self._contexto.pages)
        exibir(f"   🔎 Diagnóstico ({len(self._contexto.pages)} aba(s), {total_frames} frame(s) na página):")
        if not linhas:
            exibir('      nenhum elemento data-role="number-..." encontrado em nenhum frame.')
        for linha in linhas[:12]:
            exibir(f"      {linha}")
        exibir("      (se precisar de ajuda, mande um print desta parte)")

    # -------------------------------------------------------------------------------
    # Detecção de números novos
    # -------------------------------------------------------------------------------
    @classmethod
    def calcular_novos(cls, anterior: List[int], atual: List[int]) -> Optional[List[int]]:
        """
        Compara duas leituras da faixa (mais recente primeiro) e devolve os números que
        entraram, também do mais recente para o mais antigo:
            anterior [22, 1, 25, 28]  e  atual [7, 22, 1, 25]   ->  [7]
            anterior [22, 1, 25, 28]  e  atual [22, 22, 1, 25]  ->  [22]  (número repetido)
            anterior [22, 1, 25]      e  atual [22, 1, 25, 28]  ->  []    (a faixa só cresceu)
        Devolve None se não achar onde as duas leituras se emendam.
        """
        for k in range(len(atual)):
            sobra = atual[k:]
            m = min(len(sobra), len(anterior))
            if m >= cls.EMENDA_MINIMA and sobra[:m] == anterior[:m]:
                return atual[:k]
        return None

    def _verificar_novos(self) -> None:
        atual = self._ler_faixa_escolhida()
        if atual is None:
            self._tratar_faixa_sumida()
            return
        if self._avisou_sumico:
            exibir("✅ Faixa de resultados encontrada de novo.")
        self._sumiu_desde, self._avisou_sumico = None, False

        if atual == self._ultima:
            self._pendente = None
            return
        # Durante a animação a tela pode passar por estados intermediários. Por segurança,
        # a mudança só é aceita quando duas leituras seguidas mostram a mesma faixa.
        if atual != self._pendente:
            self._pendente = atual
            return
        self._pendente = None

        novos = self.calcular_novos(self._ultima, atual)
        if novos is None:
            exibir("⚠️  Perdi a sequência da faixa (a mesa recarregou ou ficou muito tempo sem "
                   "leitura). Vou considerar só o último número.")
            novos = atual[:1]
        self._ultima = atual
        self._fila.extend(reversed(novos))  # entrega do mais antigo para o mais novo

    def _tratar_faixa_sumida(self) -> None:
        """A faixa não apareceu nesta leitura: espera um pouco e depois procura de novo."""
        agora = time.time()
        if self._sumiu_desde is None:
            self._sumiu_desde = agora
            return
        if agora - self._sumiu_desde < self.TOLERANCIA_SUMICO:
            return
        # Se a mesa recarregou com nomes de classe novos, a "impressão digital" mudou.
        # Havendo exatamente uma faixa candidata, o robô adota ela sozinho.
        grupos = self._ler_grupos()
        if len(grupos) == 1:
            self._host, self._chave = grupos[0][0], grupos[0][1]
            return  # a próxima leitura já usa a faixa nova (e recupera os giros perdidos)
        if not self._avisou_sumico:
            exibir(f"⚠️  Não estou achando a faixa da mesa. Deixe a {self.NOME_MESA} aberta "
                   "e aparecendo no navegador (pode ficar atrás de outras janelas).")
            self._avisou_sumico = True

    # --- usados pelo processo leitor do painel (iguais para a roleta e o Bac Bo) ------------
    @staticmethod
    def visao_candidata(itens: list) -> list:
        """O que o painel mostra de cada faixa candidata (o primeiro é o mais recente)."""
        return itens[:15]

    def confirmar_faixa(self, host: str, chave: str, itens: list, invertida: bool = False) -> list:
        """Fixa a faixa escolhida e devolve o histórico do mais antigo para o mais novo."""
        faixa = list(reversed(itens)) if invertida else list(itens)
        self._host, self._chave, self._invertida, self._ultima = host, chave, invertida, faixa
        self._pendente = None
        self._fila.clear()
        return list(reversed(faixa))

    @staticmethod
    def evento_novo(item) -> dict:
        return {"tipo": "numero", "n": item}

    def obter_proximo_numero(self) -> int:
        while not self._fila:  # lê a mesa até aparecer pelo menos um número novo
            self._verificar_novos()
            if not self._fila:
                time.sleep(self.INTERVALO_LEITURA)
        return self._fila.popleft()

    @staticmethod
    def _fechar_chrome_de_verdade(navegador) -> None:
        """Fecha o Chrome do robô (não só a conexão), pedindo pela própria porta de depuração."""
        try:
            navegador.new_browser_cdp_session().send("Browser.close")
        except Exception:
            pass  # já estava fechado

    def fechar(self) -> None:
        # Com janela, só "solta" a conexão: a janela do Chrome continua aberta para a próxima
        # vez. Escondido, ninguém a vê, então o Chrome é fechado para não ficar rodando à toa.
        # No modo de teste (invisível do Playwright), fecha o navegador de vez.
        if self._navegador is not None and self.escondido:
            self._fechar_chrome_de_verdade(self._navegador)
        acoes = [self._navegador.close] if self._navegador is not None else [self._contexto.close]
        for acao in acoes + [self._pw.stop]:
            try:
                acao()
            except Exception:
                pass  # o navegador já pode ter sido fechado pelo usuário


class ColetorAPI(ColetorBase):
    """
    MODELO PRONTO de coletor real via HTTP/JSON (não é usado por padrão).
    Ele consulta a URL a cada 'intervalo_consulta' segundos e só devolve um número
    quando aparece um giro com ID diferente do último visto.
    """

    descricao = "API HTTP (JSON)"

    def __init__(self, url: str, intervalo_consulta: float = 2.0, timeout: float = 10.0,
                 cabecalhos: Optional[Dict[str, str]] = None) -> None:
        try:
            import requests  # importado aqui para o modo simulado não exigir a biblioteca
        except ImportError as erro:
            raise RuntimeError("biblioteca 'requests' não instalada. Rode: pip install requests") from erro

        self._requests = requests
        self._sessao = requests.Session()  # reaproveita a conexão (mais rápido)
        self.url = url
        self.intervalo_consulta = intervalo_consulta
        self.timeout = timeout
        self.cabecalhos = cabecalhos or {"User-Agent": "Mozilla/5.0"}
        self._ultimo_id: Optional[str] = None

    def _extrair_id_e_numero(self, dados: dict) -> Tuple[str, int]:
        """
        >>> ADAPTE ESTE MÉTODO AO JSON DO SEU SITE <<<

        Exemplo de JSON que este código espera receber:
            {"resultados": [{"id": "r-9812", "numero": 17},
                            {"id": "r-9811", "numero": 4}]}
        (o primeiro item da lista é o giro mais recente)

        Se o seu JSON não tiver um "id", use o horário do giro no lugar dele.
        """
        mais_recente = dados["resultados"][0]
        return str(mais_recente["id"]), int(mais_recente["numero"])

    def obter_proximo_numero(self) -> int:
        while True:
            try:
                resposta = self._sessao.get(self.url, headers=self.cabecalhos, timeout=self.timeout)
                resposta.raise_for_status()  # lança erro se o status HTTP for 4xx/5xx
                id_giro, numero = self._extrair_id_e_numero(resposta.json())
            except self._requests.RequestException as erro:
                raise ConnectionError(f"falha de rede ao consultar a API: {erro}") from erro
            except (KeyError, IndexError, TypeError, ValueError) as erro:
                raise ValueError(f"o JSON veio num formato diferente do esperado: {erro!r}") from erro

            if id_giro != self._ultimo_id:  # apareceu um giro novo
                self._ultimo_id = id_giro
                return numero
            time.sleep(self.intervalo_consulta)  # ainda é o mesmo giro: espera e consulta de novo


# ===================================================================================
# 7) PAINEL (tudo o que aparece na tela)
# -----------------------------------------------------------------------------------
# Concentrar os prints aqui deixa as outras classes limpas. Quer mudar o visual?
# Mexa só nesta classe.
# ===================================================================================
class Painel:
    LARGURA = 72
    LINHA_DUPLA = "=" * LARGURA
    LINHA_SIMPLES = "-" * LARGURA

    @classmethod
    def cabecalho(cls, config: Config, coletor: ColetorBase, modo: str) -> None:
        protecao = (f"proteção no 0: {formatar_reais(config.valor_protecao_zero)}"
                    if config.protecao_zero else "sem proteção no 0")
        exibir(cls.LINHA_DUPLA)
        exibir(f"🎰 ROBÔ DE ANÁLISE DE SINAIS — ROLETA EUROPEIA ({modo})")
        exibir(cls.LINHA_DUPLA)
        exibir(f"Coletor        : {coletor.descricao}")
        if isinstance(coletor, ColetorSimulado):
            exibir(f"Intervalo      : {config.intervalo_min:g} a {config.intervalo_max:g} s entre giros")
        exibir(f"Padrões        : Cor ({config.gatilho_cor} seguidas) | Dúzia ({config.gatilho_duzia} seguidas)"
               f" | Coluna ({config.gatilho_coluna} seguidas)")
        exibir(f"Banca fictícia : {formatar_reais(config.banca_inicial)} | "
               f"{formatar_reais(config.valor_por_alvo)} por alvo | {protecao}")
        mesa_real = isinstance(coletor, (ColetorManual, ColetorNavegador))
        if isinstance(coletor, ColetorManual):
            exibir("Como usar      : digite cada número que sair na mesa | d = desfazer | s = sair")
        elif isinstance(coletor, ColetorNavegador):
            exibir("Para parar     : Ctrl+C (ou feche a janela do navegador)")
        else:
            exibir("Para parar     : Ctrl+C")
        if mesa_real:
            exibir("Importante     : o robô só observa. A banca é fictícia e nada é apostado.")
        exibir(cls.LINHA_DUPLA)
        if not mesa_real:
            exibir("⏳ Aguardando o primeiro giro...\n")

    @staticmethod
    def historico_recente(historico: Deque[Giro], quantidade: int = 12) -> str:
        """Últimos giros, do mais recente (esquerda) para o mais antigo."""
        recentes = list(historico)[-quantidade:]
        return " ".join(g.rotulo() for g in reversed(recentes))

    @classmethod
    def giro(cls, numero_giro: int, giro: Giro, historico: Deque[Giro]) -> None:
        # Formato: Horário | Número | Cor | Histórico Recente
        horario = giro.horario.strftime("%H:%M:%S")
        exibir(f"[{horario}] | Giro #{numero_giro:<4} | Nº {giro.numero:>2} | "
               f"{EMOJI_COR[giro.cor]} {giro.cor:<8} | Histórico: {cls.historico_recente(historico)}")

    @classmethod
    def sinal(cls, sinal: Sinal, config: Config) -> None:
        exibir()
        exibir(cls.LINHA_DUPLA)
        exibir(f"🚨 GATILHO ATIVADO — {sinal.padrao}")
        exibir(cls.LINHA_SIMPLES)
        exibir(f"📊 Padrão detectado : {sinal.motivo}")
        exibir(f"🎯 Alvo da Aposta   : {sinal.acao}")
        exibir(f"💵 Valor sugerido   : {formatar_reais(config.valor_por_alvo)} em cada alvo")
        if config.protecao_zero:
            exibir(f"🔁 Proteção sugerida: cobrir o 🟢 0 com {formatar_reais(config.valor_protecao_zero)}")
        else:
            exibir("🔁 Proteção sugerida: nenhuma (proteção no zero desligada na Config)")
        exibir("⏭️  Entrada válida SOMENTE para o próximo giro (validação automática).")
        exibir(cls.LINHA_DUPLA)
        exibir()

    @staticmethod
    def resultado(res: ResultadoAposta, saldo: float) -> None:
        icones = {"GREEN": "✅", "GREEN NA PROTEÇÃO": "🛡️ ", "LOSS": "❌"}
        icone = icones.get(res.status, "⚠️ ")
        exibir(f"{icone} {res.status} | {res.sinal.padrao} | saiu {res.giro.rotulo()} | "
               f"{formatar_reais(res.lucro, com_sinal=True)} | Banca: {formatar_reais(saldo)}")

    @staticmethod
    def _linhas_por_padrao(banca: BancaFicticia, incluir_vazios: bool) -> Iterator[str]:
        for tipo, est in banca.estatisticas.items():
            if est.sinais == 0 and not incluir_vazios:
                continue
            mat = MATEMATICA[tipo]
            yield (f"   {NOMES_CURTOS[tipo]:<9} | {formatar_inteiro(est.sinais):>6} sinais"
                   f" | acerto {formatar_pct(est.taxa_acerto):>6}"
                   f" | teórico {formatar_pct(mat['chance_teorica']):>6}"
                   f" | mínimo p/ lucrar {formatar_pct(mat['acerto_minimo']):>6}"
                   f" | {formatar_reais(est.lucro, com_sinal=True)}")

    @classmethod
    def placar(cls, banca: BancaFicticia) -> None:
        total = banca.total()
        variacao = banca.saldo - banca.config.banca_inicial
        exibir(cls.LINHA_SIMPLES)
        exibir(f"📈 PLACAR | Banca: {formatar_reais(banca.saldo)} ({formatar_reais(variacao, com_sinal=True)})"
               f" | Sinais: {total.sinais} | ✅ {total.greens}  🛡️ {total.greens_protecao}  ❌ {total.losses}")
        for linha in cls._linhas_por_padrao(banca, incluir_vazios=False):
            exibir(linha)
        exibir(cls.LINHA_SIMPLES)
        exibir()

    @classmethod
    def relatorio_final(cls, banca: BancaFicticia, total_giros: int, duracao_s: float) -> None:
        total = banca.total()
        esperado = -total.apostado * VANTAGEM_DA_CASA
        exibir()
        exibir(cls.LINHA_DUPLA)
        exibir("🏁 RELATÓRIO FINAL")
        exibir(cls.LINHA_DUPLA)
        exibir(f"Giros analisados        : {formatar_inteiro(total_giros)}")
        exibir(f"Tempo de execução       : {duracao_s:.1f} s")
        exibir(f"Sinais disparados       : {formatar_inteiro(total.sinais)}"
               f"  (✅ {formatar_inteiro(total.greens)} | 🛡️ {formatar_inteiro(total.greens_protecao)}"
               f" | ❌ {formatar_inteiro(total.losses)})")
        exibir(f"Banca inicial → final   : {formatar_reais(banca.config.banca_inicial)} → {formatar_reais(banca.saldo)}")
        exibir(f"Menor saldo atingido    : {formatar_reais(banca.menor_saldo)}")
        if banca.quebrou_no_giro is not None:
            exibir(f"⚠️  A banca zerou no giro #{formatar_inteiro(banca.quebrou_no_giro)}")
        exibir(f"Total apostado          : {formatar_reais(total.apostado)}")
        exibir(f"Resultado real          : {formatar_reais(total.lucro, com_sinal=True)}")
        exibir(f"Esperado pela matemática: {formatar_reais(esperado, com_sinal=True)}"
               f"  (vantagem da casa de {formatar_pct(VANTAGEM_DA_CASA)} sobre o total apostado)")
        exibir(cls.LINHA_SIMPLES)
        exibir("Desempenho por padrão:")
        for linha in cls._linhas_por_padrao(banca, incluir_vazios=True):
            exibir(linha)
        exibir(cls.LINHA_SIMPLES)
        exibir("Como ler: 'acerto' é quantas vezes o alvo saiu; 'teórico' é a chance real do")
        exibir("alvo em qualquer giro; 'mínimo p/ lucrar' é o acerto necessário só para empatar.")
        exibir("Com poucos giros o acerto oscila muito; quanto mais giros, mais ele se")
        exibir("aproxima do teórico. Use o --backtest com muitos giros para ver isso.")
        exibir(cls.LINHA_DUPLA)


# ===================================================================================
# 8) MOTOR PRINCIPAL (Engine)
# -----------------------------------------------------------------------------------
# O MonitorRoleta é o "maestro": ele não sabe calcular padrão nem formatar texto,
# mas sabe a ORDEM das coisas. A cada giro:
#   1. pede um número novo ao coletor
#   2. guarda no histórico (deque de 20)
#   3. valida os sinais que estavam esperando este giro (GREEN/LOSS) e mostra o placar
#   4. pede à estratégia novos sinais e exibe os alertas
# ===================================================================================
class MonitorRoleta:
    def __init__(self, coletor: ColetorBase, estrategia: EstrategiaRoleta,
                 banca: BancaFicticia, config: Config, silencioso: bool = False) -> None:
        self.coletor = coletor
        self.estrategia = estrategia
        self.banca = banca
        self.config = config
        self.silencioso = silencioso  # True no backtest: não imprime giro a giro

        # deque com maxlen: ao chegar no 21º giro, o mais antigo sai sozinho
        self.historico: Deque[Giro] = deque(maxlen=config.tamanho_historico)
        self.sinais_pendentes: List[Sinal] = []  # sinais aguardando o próximo giro
        self.total_giros = 0
        self._falhas_seguidas = 0
        self._aviso_quebra_exibido = False
        self._estado_anterior: Optional[tuple] = None  # "foto" usada pelo comando desfazer

    # -------------------------------------------------------------------------------
    # Loop principal
    # -------------------------------------------------------------------------------
    def executar(self, limite_giros: Optional[int] = None, modo: str = "AO VIVO") -> None:
        inicio = time.time()
        if self.silencioso:
            exibir(f"🧪 BACKTEST: simulando {formatar_inteiro(limite_giros or 0)} giros...")
        else:
            Painel.cabecalho(self.config, self.coletor, modo)

        try:
            self._carregar_historico_inicial()
            while True:  # roda até Ctrl+C / "s", até o limite de giros ou até falhas demais
                if limite_giros is not None and self.total_giros >= limite_giros:
                    break
                self._processar_um_giro()
                if self.silencioso and limite_giros:
                    self._mostrar_progresso(limite_giros)
        except (KeyboardInterrupt, PedidoEncerrar):
            exibir("\n⏹️  Robô encerrado pelo usuário.")
        except RuntimeError as erro:
            exibir(f"\n⛔ Robô encerrado: {erro}")
        finally:
            # o relatório aparece SEMPRE, não importa como o loop terminou
            Painel.relatorio_final(self.banca, self.total_giros, time.time() - inicio)
            self.coletor.fechar()  # ex.: fecha o navegador do modo automático

    # -------------------------------------------------------------------------------
    # Um ciclo completo (um giro)
    # -------------------------------------------------------------------------------
    def _carregar_historico_inicial(self) -> None:
        """Carrega os números que a mesa já mostrava (sem apostar neles)."""
        numeros = self.coletor.ler_historico_inicial()
        if not numeros:
            if self.coletor.permite_desfazer:
                exibir()
            return
        for numero in numeros:
            self.historico.append(Giro.a_partir_do_numero(numero))
        exibir(f"\n✅ Histórico carregado (mais recente à esquerda): "
               f"{Painel.historico_recente(self.historico)}\n")
        # Se o histórico carregado já forma um padrão, o alerta vale para o próximo giro
        self.sinais_pendentes = self.estrategia.analisar(self.historico, self.total_giros)
        for sinal in self.sinais_pendentes:
            Painel.sinal(sinal, self.config)

    def _processar_um_giro(self) -> None:
        # ETAPA 1: coletar o número novo (no modo manual, "d" pede para desfazer)
        try:
            giro = self._coletar_giro()
        except PedidoDesfazer:
            self._desfazer_ultimo_giro()
            return
        if giro is None:
            return  # a coleta falhou; o próximo ciclo tenta de novo

        # Antes de mexer em qualquer coisa, tira uma "foto" do estado atual.
        # Se você digitar "d" no próximo prompt, o robô volta exatamente para ela.
        if self.coletor.permite_desfazer:
            self._estado_anterior = (copy.deepcopy(self.banca), self.historico.copy(),
                                     list(self.sinais_pendentes), self.total_giros,
                                     self._aviso_quebra_exibido)

        # ETAPA 2: registrar no histórico e mostrar o log do giro
        self.total_giros += 1
        self.historico.append(giro)
        if not self.silencioso:
            Painel.giro(self.total_giros, giro, self.historico)

        # ETAPA 3: validar os sinais que foram emitidos no giro anterior
        self._validar_sinais_pendentes(giro)

        # ETAPA 4: procurar sinais novos (eles serão validados no PRÓXIMO giro)
        novos_sinais = self.estrategia.analisar(self.historico, self.total_giros)
        if not self.silencioso:
            for sinal in novos_sinais:
                Painel.sinal(sinal, self.config)
        self.sinais_pendentes = novos_sinais

    def _coletar_giro(self) -> Optional[Giro]:
        """Pede um número ao coletor, com tratamento de erro e nova tentativa."""
        try:
            numero = self.coletor.obter_proximo_numero()
            giro = Giro.a_partir_do_numero(numero)
            self._falhas_seguidas = 0
            return giro
        except ComandoUsuario:
            raise  # "d" e "s" não são falhas: passam direto para quem sabe tratá-los
        except Exception as erro:  # rede, formato do JSON, número inválido...
            self._falhas_seguidas += 1
            exibir(f"⚠️  Falha na coleta ({self._falhas_seguidas}/{self.config.max_falhas_seguidas}): "
                   f"{type(erro).__name__}: {erro}")
            if self._falhas_seguidas >= self.config.max_falhas_seguidas:
                raise RuntimeError("falhas demais seguidas na coleta de dados.") from erro
            espera = min(5 * self._falhas_seguidas, 30)  # espera cada vez maior, até 30 s
            exibir(f"   Tentando de novo em {espera} s...")
            time.sleep(espera)
            return None

    def _desfazer_ultimo_giro(self) -> None:
        """Volta para a "foto" tirada antes do último número (banca, histórico e sinais)."""
        if self._estado_anterior is None:
            exibir("   ⚠️  Nada para desfazer (dá para desfazer só o último número, uma vez).")
            return
        (self.banca, self.historico, self.sinais_pendentes,
         self.total_giros, self._aviso_quebra_exibido) = self._estado_anterior
        self._estado_anterior = None
        exibir(f"↩️  Último número desfeito. Histórico: "
               f"{Painel.historico_recente(self.historico) or '(vazio)'} | "
               f"Banca: {formatar_reais(self.banca.saldo)}")
        for sinal in self.sinais_pendentes:  # relembra os alertas que voltaram a valer
            exibir(f"   🚨 Alerta valendo de novo: {sinal.padrao} → {sinal.acao}")
        exibir()

    def _validar_sinais_pendentes(self, giro: Giro) -> None:
        """Confere GREEN/LOSS dos sinais do giro anterior e atualiza a banca."""
        if not self.sinais_pendentes:
            return
        for sinal in self.sinais_pendentes:
            try:
                resultado = self.banca.liquidar(sinal, giro, self.total_giros)
            except Exception as erro:
                exibir(f"⚠️  Erro ao validar {sinal.padrao}: {erro}")
                continue
            if not self.silencioso:
                Painel.resultado(resultado, self.banca.saldo)

        if not self.silencioso:
            Painel.placar(self.banca)
            if self.banca.quebrou_no_giro is not None and not self._aviso_quebra_exibido:
                exibir("⚠️  BANCA FICTÍCIA ZERADA. O robô continua rodando só para as estatísticas.\n")
                self._aviso_quebra_exibido = True
        self.sinais_pendentes = []

    def _mostrar_progresso(self, limite: int) -> None:
        """No backtest, mostra o andamento a cada 10%."""
        passo = max(1, limite // 10)
        if self.total_giros % passo == 0 or self.total_giros == limite:
            pct = self.total_giros / limite
            exibir(f"   ... {formatar_pct(pct):>6} | giro {formatar_inteiro(self.total_giros)}"
                   f" | banca {formatar_reais(self.banca.saldo)}")


# ===================================================================================
# 9) PONTO DE PARTIDA
# ===================================================================================
def configurar_terminal() -> None:
    """Força UTF-8 na saída para os emojis não quebrarem no Windows."""
    for fluxo in (sys.stdout, sys.stderr):
        try:
            fluxo.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass  # terminal antigo: segue sem mudar (no pior caso, emoji aparece como '?')


def ler_argumentos(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Robô local de análise de sinais de roleta europeia.")
    parser.add_argument("--navegador", action="store_true",
                        help="mesa real AUTOMÁTICA: lê a Immersive Roulette aberta no navegador")
    parser.add_argument("--url", metavar="ENDERECO",
                        help="no modo --navegador, endereço que já abre na janela (opcional)")
    parser.add_argument("--headless", action="store_true", help=argparse.SUPPRESS)  # só para testes
    parser.add_argument("--manual", action="store_true",
                        help="mesa real: você digita cada número que sai (ex.: Immersive Roulette)")
    parser.add_argument("--mesa", default="Immersive Roulette", metavar="NOME",
                        help="nome da mesa exibido no modo manual (padrão: Immersive Roulette)")
    parser.add_argument("--simulador", action="store_true",
                        help="simulador ao vivo: 1 giro a cada 10 a 15 s")
    parser.add_argument("--rapido", action="store_true",
                        help="simulador acelerado: 1 giro por segundo")
    parser.add_argument("--giros", type=int, metavar="N",
                        help="para sozinho depois de N giros")
    parser.add_argument("--backtest", type=int, metavar="N",
                        help="simula N giros instantaneamente e mostra só o relatório")
    parser.add_argument("--semente", type=int, metavar="S",
                        help="semente aleatória (mesma semente = mesma sequência de números)")
    parser.add_argument("--sem-emoji", action="store_true", help="troca os emojis por texto")
    parser.add_argument("--com-emoji", action="store_true", help="força o uso de emojis")
    parser.add_argument("--web", action="store_true",
                        help="abre o painel visual no navegador, rodando escondido (precisa: pip install streamlit)")
    parser.add_argument("--atalho", action="store_true",
                        help="cria na Área de Trabalho um atalho que abre o painel direto (Windows)")
    parser.add_argument("--atualizar", action="store_true",
                        help="baixa a versão mais nova do robô no GitHub e troca este arquivo")
    parser.add_argument("--jogo", choices=["roleta", "bacbo"], default="roleta",
                        help="jogo analisado (padrão: roleta). No terminal, o Bac Bo tem o --backtest")
    parser.add_argument("--leitor-json", action="store_true", help=argparse.SUPPRESS)  # usado pelo painel
    parser.add_argument("--escondido", action="store_true",
                        help="no modo --navegador, abre o Chrome do robô sem janela visível")
    parser.add_argument("--auto-confirmar", action="store_true", help=argparse.SUPPRESS)  # usado pelo painel
    return parser.parse_args(argv)


def menu_inicial() -> Optional[List[str]]:
    """
    Menu para quem abre o arquivo com dois cliques (sem digitar comandos).
    Devolve os argumentos equivalentes à opção escolhida, ou None para sair.
    """
    exibir("=" * 72)
    exibir("🎰 ROBÔ DE ANÁLISE DE SINAIS — ROLETA EUROPEIA")
    exibir("=" * 72)
    exibir("  1) Mesa real AUTOMÁTICA — lê a Immersive Roulette no navegador")
    exibir("  2) Mesa real manual — você digita os números que saem")
    exibir("  3) Simulador ao vivo (1 giro a cada 10 a 15 s)")
    exibir("  4) Simulador acelerado (1 giro por segundo)")
    exibir("  5) Backtest (simula milhares de giros de uma vez)")
    exibir("  6) Painel visual no navegador (roda escondido, sem esta janela)")
    exibir("  7) Criar atalho do painel na Área de Trabalho")
    exibir("  8) Atualizar o robô (baixa a versão mais nova do GitHub)")
    exibir("  0) Sair")
    exibir("=" * 72)
    while True:
        try:
            escolha = input("Escolha uma opção: ").strip()
        except EOFError:
            return None
        if escolha == "1":
            return ["--navegador"]
        if escolha == "2":
            return ["--manual"]
        if escolha == "3":
            return ["--simulador"]
        if escolha == "4":
            return ["--rapido"]
        if escolha == "5":
            giros = input("Quantos giros? (Enter = 100000): ").strip().replace(".", "") or "100000"
            if giros.isdigit() and int(giros) > 0:
                return ["--backtest", giros]
            exibir("⚠️  Digite um número inteiro positivo.")
            continue
        if escolha == "6":
            return ["--web"]
        if escolha == "7":
            return ["--atalho"]
        if escolha == "8":
            return ["--atualizar"]
        if escolha == "0":
            return None
        exibir("⚠️  Opção inválida. Digite um número de 0 a 8.")


def pausar_antes_de_fechar() -> None:
    """Segura a janela aberta no fim, para dar tempo de ler o relatório (dois cliques)."""
    try:
        input("\nPressione Enter para fechar...")
    except (EOFError, KeyboardInterrupt):
        pass


def rodar(args: argparse.Namespace) -> None:
    """Monta as peças conforme o modo escolhido e liga o motor."""
    if args.jogo == "bacbo":
        rodar_bacbo_terminal(args)
        return
    modo_backtest = args.backtest is not None

    # --- Monta a configuração conforme o modo escolhido -----------------------------
    try:
        if sum([args.navegador, args.manual, modo_backtest]) > 1:
            raise ValueError("escolha só um modo: --navegador, --manual ou --backtest.")
        ajustes = {}
        if args.rapido:
            ajustes.update(intervalo_min=1.0, intervalo_max=1.0)
        if modo_backtest:
            if args.backtest <= 0:
                raise ValueError("--backtest precisa de um número positivo de giros.")
            ajustes.update(intervalo_min=0.0, intervalo_max=0.0)
        if args.giros is not None and args.giros <= 0:
            raise ValueError("--giros precisa ser um número positivo.")
        config = Config(**ajustes)
    except ValueError as erro:
        exibir(f"⛔ Configuração inválida: {erro}")
        sys.exit(1)

    # -------------------------------------------------------------------------------
    # ⚠️ AVISO: É AQUI QUE VOCÊ TROCA A FONTE DOS NÚMEROS PELO SEU SCRAPING
    #    (veja o bloco "AVISO: COLE SEU SCRAPING AQUI" na seção 6)
    # -------------------------------------------------------------------------------
    coletor: ColetorBase
    if args.navegador:
        exibir("🌐 Abrindo o navegador...")
        try:
            coletor = ColetorNavegador(url=args.url, headless=args.headless, escondido=args.escondido)
        except RuntimeError as erro:
            exibir(f"⛔ {erro}")
            sys.exit(1)
        modo = f"MESA REAL AUTOMÁTICA — {args.mesa.upper()}"
    elif args.manual:
        coletor = ColetorManual(nome_mesa=args.mesa)
        modo = f"MESA REAL — {args.mesa.upper()}"
    else:
        coletor = ColetorSimulado(config.intervalo_min, config.intervalo_max, semente=args.semente)
        modo = "AO VIVO — ACELERADO" if args.rapido else "AO VIVO"
    # coletor = ColetorAPI(url="https://SEU-ENDPOINT-AQUI", intervalo_consulta=2.0)

    # --- Monta as peças e liga o motor ---------------------------------------------
    monitor = MonitorRoleta(
        coletor=coletor,
        estrategia=EstrategiaRoleta(config),
        banca=BancaFicticia(config),
        config=config,
        silencioso=modo_backtest,
    )
    if modo_backtest:
        monitor.executar(limite_giros=args.backtest, modo="BACKTEST")
    else:
        monitor.executar(limite_giros=args.giros, modo=modo)


def main() -> None:
    global USAR_EMOJI
    configurar_terminal()
    USAR_EMOJI = terminal_mostra_emoji()

    # Sem nenhum argumento e com teclado disponível = provavelmente dois cliques: abre o menu
    veio_do_menu = len(sys.argv) == 1 and sys.stdin.isatty()
    try:
        if veio_do_menu:
            argv = menu_inicial()
            if argv is None:
                veio_do_menu = False  # escolheu "Sair": fecha direto, sem pausa
                return
        else:
            argv = sys.argv[1:]

        args = ler_argumentos(argv)
        if args.leitor_json:  # chamado pelo painel web: lê a mesa e responde em JSON
            veio_do_menu = False
            modo_leitor_json(args.url, escondido=args.escondido, auto_confirmar=args.auto_confirmar, jogo=args.jogo)
            return
        if args.web:
            if abrir_painel_web():
                veio_do_menu = False  # deu certo: a janela preta pode fechar sozinha
            return
        if args.atalho:
            criar_atalho_area_de_trabalho()
            return
        if args.atualizar:
            exibir("🌐 Procurando a versão mais nova no GitHub...")
            ok, trocou, mensagem = atualizar_robo()
            avisar(("✅ " if ok else "") + mensagem, erro=not ok)
            if trocou:
                exibir("   Feche esta janela e abra o robô de novo para usar a versão nova.")
            return
        if args.sem_emoji:
            USAR_EMOJI = False
        if args.com_emoji:
            USAR_EMOJI = True
        rodar(args)
    finally:
        if veio_do_menu:
            pausar_antes_de_fechar()


# -----------------------------------------------------------------------------------
# Painel em segundo plano (sem janela preta)
# -----------------------------------------------------------------------------------
# A opção 6 (ou --web, ou o atalho da Área de Trabalho) liga o servidor do painel
# ESCONDIDO e abre o navegador. A janela preta pode fechar: o painel continua rodando
# até você clicar em "Desligar o painel" na barra lateral (ou desligar o PC).
# Se o painel já estiver ligado, ela só abre a página de novo.
# -----------------------------------------------------------------------------------
def _pasta_do_robo() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def _arquivo_porta() -> str:
    """Arquivo onde o robô anota em qual porta o painel está rodando."""
    return os.path.join(_pasta_do_robo(), "painel_robo.porta")


def avisar(mensagem: str, erro: bool = False) -> None:
    """Mostra a mensagem no terminal; sem terminal (atalho), mostra numa janelinha do Windows."""
    exibir(("⛔ " if erro else "") + mensagem)
    if sys.stdout is None and os.name == "nt":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, mensagem, "Robô de Roleta", 0x10 if erro else 0x40)
        except Exception:
            pass


def _painel_respondendo(porta: int, espera: float = 1.5) -> bool:
    """Pergunta ao painel se ele está de pé (endereço de saúde do Streamlit)."""
    abridor = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # ignora proxy: é local
    try:
        with abridor.open(f"http://127.0.0.1:{porta}/_stcore/health", timeout=espera) as resposta:
            return resposta.status == 200
    except Exception:
        return False


def _porta_livre(porta: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", porta))
            return True
        except OSError:
            return False


def _python_sem_janela() -> str:
    """No Windows, o pythonw.exe roda programas sem abrir janela preta."""
    if os.name == "nt":
        candidato = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        if os.path.isfile(candidato):
            return candidato
    return sys.executable


def abrir_painel_web() -> bool:
    """Liga o painel escondido e abre o navegador. Devolve True se deu certo."""
    if importlib.util.find_spec("streamlit") is None:
        avisar("O painel visual precisa do Streamlit. Abra o terminal e rode:  py -m pip install streamlit", erro=True)
        return False

    # 1) Já está ligado? Então só abre a página.
    candidatas = []
    try:
        with open(_arquivo_porta(), encoding="utf-8") as arq:
            candidatas.append(int(arq.read().strip()))
    except (OSError, ValueError):
        pass
    for porta in dict.fromkeys(candidatas + [8501]):
        if _painel_respondendo(porta):
            webbrowser.open(f"http://localhost:{porta}")
            avisar(f"O painel já estava ligado. Abri a página: http://localhost:{porta}")
            return True

    # 2) Escolhe uma porta livre e liga o servidor escondido
    porta = next((p for p in range(8501, 8511) if _porta_livre(p)), None)
    if porta is None:
        avisar("Não achei uma porta livre entre 8501 e 8510 para o painel.", erro=True)
        return False
    comando = [_python_sem_janela(), "-m", "streamlit", "run", os.path.abspath(__file__),
               "--server.headless", "true", "--server.port", str(porta),
               "--browser.gatherUsageStats", "false",
               "--theme.base", "dark", "--theme.primaryColor", "#FF3B55",
               "--theme.backgroundColor", "#0B0D12", "--theme.secondaryBackgroundColor", "#141821",
               "--theme.textColor", "#EEF0F4"]
    if os.name == "nt":  # processo solto: continua vivo quando a janela preta fecha
        opcoes = {"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP}
    else:
        opcoes = {"start_new_session": True}
    arquivo_log = os.path.join(_pasta_do_robo(), "painel_robo.log")  # para descobrir problemas
    ambiente = dict(os.environ, ROBO_ROLETA_LOCAL="1")  # avisa o painel que ele roda no seu PC
    try:
        with open(arquivo_log, "w", encoding="utf-8") as log:
            servidor = subprocess.Popen(comando, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                        cwd=_pasta_do_robo(), close_fds=True, env=ambiente, **opcoes)
    except OSError as erro:
        avisar(f"Não consegui ligar o painel: {erro}", erro=True)
        return False

    exibir("🌐 Ligando o painel (leva alguns segundos)...")
    prazo = time.time() + 45
    while time.time() < prazo:
        if _painel_respondendo(porta):
            try:
                with open(_arquivo_porta(), "w", encoding="utf-8") as arq:
                    arq.write(str(porta))
            except OSError:
                pass
            url = f"http://localhost:{porta}"
            webbrowser.open(url)
            exibir(f"✅ Painel aberto em {url}")
            exibir("   Pode fechar esta janela: o painel continua rodando escondido.")
            exibir("   Para desligar, use o botão 'Desligar o painel' na barra lateral.")
            return True
        if servidor.poll() is not None:
            break  # o servidor morreu ao ligar: não adianta esperar mais
        time.sleep(0.5)

    try:
        with open(arquivo_log, encoding="utf-8", errors="replace") as log:
            final = "".join(log.readlines()[-12:])
    except OSError:
        final = "(sem log)"
    avisar(f"O painel não respondeu a tempo. Últimas linhas do log ({arquivo_log}):\n{final}", erro=True)
    return False


# -----------------------------------------------------------------------------------
# Atualização automática: baixa a versão mais nova publicada no GitHub
# -----------------------------------------------------------------------------------
URL_ATUALIZACAO = "https://raw.githubusercontent.com/gfilipe434-dot/robo_roleta/main/robo_roleta.py"


def atualizar_robo(url: str = URL_ATUALIZACAO) -> Tuple[bool, bool, str]:
    """
    Baixa o robo_roleta.py mais novo do GitHub e troca este arquivo por ele.
    Antes de trocar, confere se o arquivo baixado é mesmo o robô (e se não tem erro de
    digitação no código) e guarda a versão atual como <nome>_anterior.py, por segurança.
    Devolve (deu_certo, trocou_o_arquivo, mensagem).
    """
    destino = os.path.abspath(__file__)
    # O "?t=..." no fim pede ao GitHub a cópia mais recente, e não uma guardada em cache
    endereco = url + ("&" if "?" in url else "?") + f"t={int(time.time())}"
    try:
        with urllib.request.urlopen(endereco, timeout=25) as resposta:
            novo = resposta.read()
    except Exception as erro:
        return False, False, f"Não consegui baixar a versão nova ({erro}). Confira a internet e tente de novo."
    try:
        texto = novo.decode("utf-8")
        compile(texto, destino, "exec")  # garante que o código baixado não está quebrado
        if "class EstrategiaRoleta" not in texto or "def app_web" not in texto:
            raise ValueError("o conteúdo não é o robô")
    except Exception as erro:
        return False, False, f"O arquivo baixado não parece o robô ({erro}). Nada foi trocado."
    with open(destino, "rb") as arq:
        atual = arq.read()
    if atual.replace(b"\r\n", b"\n") == novo.replace(b"\r\n", b"\n"):
        return True, False, "Você já está com a versão mais nova."
    base, extensao = os.path.splitext(destino)
    temporario = base + ".baixando" + extensao
    try:
        with open(base + "_anterior" + extensao, "wb") as arq:  # cópia de segurança
            arq.write(atual)
        with open(temporario, "wb") as arq:
            arq.write(novo)
        os.replace(temporario, destino)  # troca de uma vez só (nunca fica meio arquivo)
    except OSError as erro:
        return False, False, f"Não consegui gravar o arquivo novo ({erro}). Nada foi trocado."
    return True, True, ("Robô atualizado para a versão mais nova. "
                        f"A anterior ficou guardada como {os.path.basename(base)}_anterior{extensao}.")


def _comando_atalho(destino_python: str, script: str) -> List[str]:
    """Monta o comando do PowerShell que cria o atalho (separado para poder testar)."""
    aspas = lambda t: t.replace("'", "''")  # aspas simples dentro de texto do PowerShell
    pasta = os.path.dirname(script)
    ps = ("$d=[Environment]::GetFolderPath('Desktop');"
          "$s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d 'Robo de Roleta.lnk'));"
          f"$s.TargetPath='{aspas(destino_python)}';"
          f"$s.Arguments='\"{aspas(script)}\" --web';"
          f"$s.WorkingDirectory='{aspas(pasta)}';"
          f"$s.IconLocation='{aspas(destino_python)},0';"
          "$s.Description='Abre o painel do Robo de Roleta';$s.Save()")
    return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps]


def criar_atalho_area_de_trabalho() -> None:
    """Cria o atalho 'Robo de Roleta' na Área de Trabalho, que abre o painel sem janela preta."""
    if os.name != "nt":
        exibir("O atalho automático é só para Windows. Use:  python robo_roleta.py --web")
        return
    comando = _comando_atalho(_python_sem_janela(), os.path.abspath(__file__))
    try:
        resultado = subprocess.run(comando, capture_output=True, text=True, timeout=30,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired) as erro:
        avisar(f"Não consegui criar o atalho: {erro}", erro=True)
        return
    if resultado.returncode == 0:
        exibir("✅ Atalho 'Robo de Roleta' criado na Área de Trabalho.")
        exibir("   Dois cliques nele abrem o painel direto, sem janela preta.")
        exibir("   Se você mover o robo_roleta.py de pasta, crie o atalho de novo.")
    else:
        avisar(f"O Windows não deixou criar o atalho: {resultado.stderr.strip()[:300]}", erro=True)


# ===================================================================================
# 10) PAINEL VISUAL NO NAVEGADOR (Streamlit)
# -----------------------------------------------------------------------------------
# Como abrir (precisa de:  pip install streamlit ; e  pip install playwright  para o
# modo automático):
#     python robo_roleta.py --web        (ou opção 6 do menu: já abre no tema escuro)
#     streamlit run robo_roleta.py       (forma direta)
#
# O painel usa EXATAMENTE as mesmas classes do terminal (Config, Giro, Sinal,
# EstrategiaRoleta, BancaFicticia, ColetorSimulado, ColetorNavegador...). Só muda a
# forma de mostrar. Por isso os testes de aceitação continuam batendo.
#
# Peças desta seção:
#   MotorWeb .............. o mesmo ciclo do MonitorRoleta, mas devolve dados em vez de imprimir
#   executar_backtest() ... backtest do painel (1.000.000 giros, semente 42 -> -R$ 90.804,00)
#   modo_leitor_json() .... processo separado que lê a mesa pelo Chrome e manda JSON
#   LeitorProcesso ........ lado do painel: liga esse processo e recebe os números
#   SessaoWeb ............. estado único do painel (continua vivo se você recarregar a página)
#   Html .................. pedaços visuais: pedras, cartões, alertas, tabela e gráfico
#   app_web() ............. a tela
#
# Por que a leitura do Chrome roda num PROCESSO SEPARADO? O Streamlit executa o
# script de novo a cada clique, em threads diferentes, e o Playwright exige ficar
# sempre na mesma thread (e no Windows ele não consegue abrir o Chrome de dentro do
# Streamlit). Num processo à parte, a leitura nunca trava a tela e vice-versa: os dois
# conversam por linhas de texto em JSON.
# ===================================================================================
class MotorWeb:
    """Mesmo ciclo do MonitorRoleta (coleta -> histórico -> liquida -> analisa), sem imprimir."""

    LIMITE_FEED = 300      # quantos resultados recentes guardar para a tela
    LIMITE_CURVA = 3000    # pontos máximos da curva da sessão

    def __init__(self, config: Config, registrar: bool = True) -> None:
        self.config = config
        self.estrategia = EstrategiaRoleta(config)
        self.banca = BancaFicticia(config)
        self.historico: Deque[Giro] = deque(maxlen=config.tamanho_historico)
        self.pendentes: List[Sinal] = []
        self.total_giros = 0
        self.registrar = registrar  # False no backtest (mais rápido)
        self.resultados: Deque[ResultadoAposta] = deque(maxlen=self.LIMITE_FEED)
        self.curva: List[Tuple[int, float, float]] = [(0, 0.0, 0.0)]
        self.iniciada_em = datetime.now()
        self._foto: Optional[tuple] = None

    def carregar_historico(self, numeros: List[int]) -> None:
        """Números que a mesa já mostrava (do mais antigo para o mais novo), sem apostar."""
        for numero in numeros:
            self.historico.append(Giro.a_partir_do_numero(numero))
        self.pendentes = self.estrategia.analisar(self.historico, self.total_giros)

    def processar(self, numero: int, permitir_desfazer: bool = False) -> Tuple[Giro, List[ResultadoAposta]]:
        """Um giro completo, na mesma ordem do terminal. Devolve o giro e os resultados."""
        giro = Giro.a_partir_do_numero(numero)  # valida ANTES de mexer em qualquer coisa
        if permitir_desfazer:
            self._foto = (copy.deepcopy(self.banca), self.historico.copy(), list(self.pendentes),
                          self.total_giros, list(self.resultados), list(self.curva))
        self.total_giros += 1
        self.historico.append(giro)

        resultados: List[ResultadoAposta] = []
        for sinal in self.pendentes:  # liquida os sinais do giro anterior
            try:
                resultados.append(self.banca.liquidar(sinal, giro, self.total_giros))
            except Exception as erro:
                exibir(f"⚠️  Erro ao validar {sinal.padrao}: {erro}")
        self.pendentes = self.estrategia.analisar(self.historico, self.total_giros)

        if self.registrar:
            self.resultados.extend(resultados)
            total = self.banca.total()
            self.curva.append((self.total_giros, total.lucro, -total.apostado * VANTAGEM_DA_CASA))
            if len(self.curva) > self.LIMITE_CURVA:  # afina a curva mantendo o começo e o fim
                self.curva = self.curva[:1] + self.curva[1:-1:2] + self.curva[-1:]
        return giro, resultados

    def desfazer(self) -> bool:
        """Volta para antes do último número (só uma vez). Devolve False se não havia o que desfazer."""
        if self._foto is None:
            return False
        banca, historico, pendentes, total, resultados, curva = self._foto
        self.banca, self.historico, self.pendentes, self.total_giros = banca, historico, pendentes, total
        self.resultados = deque(resultados, maxlen=self.LIMITE_FEED)
        self.curva = curva
        self._foto = None
        return True


def executar_backtest(giros: int, semente: Optional[int], config: Optional[Config] = None,
                      ao_progredir=None) -> MotorWeb:
    """
    Backtest do painel. Usa o mesmo ColetorSimulado do terminal e o mesmo ciclo, então
    1.000.000 de giros com semente 42 dá 195.368 sinais e -R$ 90.804,00, igual ao terminal.
    """
    config = config or Config(intervalo_min=0.0, intervalo_max=0.0)
    coletor = ColetorSimulado(0.0, 0.0, semente=semente)
    motor = MotorWeb(config, registrar=False)
    passo = max(1, giros // 100)
    curva = [(0, 0.0, 0.0)]
    for g in range(1, giros + 1):
        motor.processar(coletor.obter_proximo_numero())
        if g % passo == 0 or g == giros:
            total = motor.banca.total()
            curva.append((g, total.lucro, -total.apostado * VANTAGEM_DA_CASA))
            if ao_progredir is not None:
                ao_progredir(g / giros)
    motor.curva = curva
    return motor


def modo_leitor_json(url: Optional[str], escondido: bool = False, auto_confirmar: bool = False,
                     jogo: str = "roleta") -> None:
    """
    Roda como processo separado, chamado pelo painel com --leitor-json. Lê a mesa pelo
    Chrome (ColetorNavegador) e escreve uma linha JSON por evento:
        {"tipo": "fase", "fase": "conectando" | "procurando" | "lendo"}
        {"tipo": "candidatas", "grupos": [[22, 1, 25, ...], ...]}   faixas achadas na página
        {"tipo": "diagnostico", "linhas": [...]}                    quando não acha nada
        {"tipo": "historico", "numeros": [...]}                     após confirmar a faixa
        {"tipo": "numero", "n": 17}                                 cada número novo
        {"tipo": "rodada", "r": "P", "soma": 7}                     cada rodada nova (Bac Bo)
        {"tipo": "msg" | "erro" | "fim", ...}
    E recebe comandos JSON pela entrada padrão:
        {"cmd": "confirmar", "indice": 0, "invertida": false} | {"cmd": "procurar"} | {"cmd": "parar"}
    """
    global SAIDA_JSON
    SAIDA_JSON = True

    def emitir(**dados) -> None:
        print(json.dumps(dados, ensure_ascii=False), flush=True)

    comandos: "queue.Queue[dict]" = queue.Queue()

    def ler_comandos() -> None:
        for linha in sys.stdin:
            try:
                comandos.put(json.loads(linha))
            except ValueError:
                pass
        comandos.put({"cmd": "parar"})  # o painel fechou: o leitor encerra junto

    def proximo_comando(espera: float) -> Optional[dict]:
        try:
            return comandos.get(timeout=espera)
        except queue.Empty:
            return None

    threading.Thread(target=ler_comandos, daemon=True).start()
    emitir(tipo="fase", fase="conectando")
    try:
        classe = ColetorNavegadorBacBo if jogo == "bacbo" else ColetorNavegador
        coletor = classe(url=url, escondido=escondido)
    except Exception as erro:
        emitir(tipo="erro", texto=str(erro))
        return

    try:
        while True:  # cada volta: acha a faixa (calibração) e depois lê os números
            emitir(tipo="fase", fase="procurando")
            candidatas: List[Tuple[str, str, List[int]]] = []
            ultimo_envio: Optional[list] = None
            ultimo_diagnostico = time.time()
            ultima_vista: Optional[Tuple[str, str]] = None
            confirmado = False
            while not confirmado:
                grupos = coletor._ler_grupos()
                visao = [coletor.visao_candidata(numeros) for _host, _chave, numeros in grupos]
                if visao != ultimo_envio:
                    emitir(tipo="candidatas", grupos=visao)
                    ultimo_envio, candidatas = visao, grupos
                if not grupos and time.time() - ultimo_diagnostico > 20:
                    linhas: List[str] = []
                    coletor._ler_grupos(diagnostico=linhas)
                    emitir(tipo="diagnostico", linhas=linhas[:12])
                    ultimo_diagnostico = time.time()
                comando = proximo_comando(1.0)
                # Confirmar sozinho: se há UMA faixa só e ela foi vista em duas leituras
                # seguidas, confirma como se você tivesse clicado em "Confere".
                if comando is None and auto_confirmar and len(grupos) == 1:
                    vista = (grupos[0][0], grupos[0][1])
                    if vista == ultima_vista:
                        candidatas = grupos
                        comando = {"cmd": "confirmar", "indice": 0, "invertida": False}
                        emitir(tipo="msg", texto="Faixa encontrada e confirmada sozinha.")
                    ultima_vista = vista
                elif len(grupos) != 1:
                    ultima_vista = None
                if not comando:
                    continue
                if comando.get("cmd") == "parar":
                    return
                if comando.get("cmd") == "confirmar":
                    indice, invertida = int(comando.get("indice", 0)), bool(comando.get("invertida"))
                    if 0 <= indice < len(candidatas):
                        host, chave, numeros = candidatas[indice]
                        emitir(tipo="historico", numeros=coletor.confirmar_faixa(host, chave, numeros, invertida))
                        confirmado = True

            emitir(tipo="fase", fase="lendo")
            while True:
                comando = proximo_comando(coletor.INTERVALO_LEITURA)
                if comando and comando.get("cmd") == "parar":
                    return
                if comando and comando.get("cmd") == "procurar":
                    break  # volta para a calibração
                coletor._verificar_novos()
                while coletor._fila:
                    emitir(**coletor.evento_novo(coletor._fila.popleft()))
    except PedidoEncerrar:
        emitir(tipo="fim", motivo="O navegador foi fechado.")
    except Exception as erro:
        emitir(tipo="erro", texto=f"{type(erro).__name__}: {erro}")
    finally:
        coletor.fechar()


class LeitorProcesso:
    """Lado do painel: liga o processo leitor e guarda o que ele manda."""

    def __init__(self, url: Optional[str] = None, escondido: bool = False, auto_confirmar: bool = False,
                 jogo: str = "roleta") -> None:
        comando = [sys.executable, "-u", os.path.abspath(__file__), "--leitor-json", "--jogo", jogo]
        if url:
            comando += ["--url", url]
        if escondido:
            comando.append("--escondido")
        if auto_confirmar:
            comando.append("--auto-confirmar")
        self.escondido = escondido
        opcoes = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
        self.proc = subprocess.Popen(comando, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                     errors="replace", bufsize=1, **opcoes)
        self.fase = "iniciando"
        self.candidatas: List[List[int]] = []
        self.diagnostico: List[str] = []
        self.mensagens: Deque[Tuple[str, str]] = deque(maxlen=30)
        self.erro: Optional[str] = None
        self._historico: Optional[List[int]] = None
        self._numeros: "queue.Queue[int]" = queue.Queue()
        self._trava = threading.Lock()
        threading.Thread(target=self._ler_saida, daemon=True).start()

    def _ler_saida(self) -> None:
        for linha in self.proc.stdout:
            linha = linha.strip()
            if not linha:
                continue
            try:
                evento = json.loads(linha)
            except ValueError:
                evento = {"tipo": "msg", "texto": linha}  # aviso solto (ex.: do Playwright)
            tipo = evento.get("tipo")
            with self._trava:
                if tipo == "fase":
                    self.fase = evento.get("fase", self.fase)
                elif tipo == "candidatas":
                    self.candidatas = evento.get("grupos", [])
                elif tipo == "diagnostico":
                    self.diagnostico = evento.get("linhas", [])
                elif tipo == "historico":
                    self._historico = evento.get("numeros", [])
                elif tipo == "numero":
                    self._numeros.put(int(evento["n"]))
                elif tipo == "rodada":
                    self._numeros.put((str(evento.get("r", "")), evento.get("soma")))
                elif tipo == "erro":
                    self.fase, self.erro = "erro", evento.get("texto", "erro desconhecido")
                elif tipo == "fim":
                    self.fase = "fim"
                    self.mensagens.append((datetime.now().strftime("%H:%M:%S"), evento.get("motivo", "")))
                else:
                    self.mensagens.append((datetime.now().strftime("%H:%M:%S"), str(evento.get("texto", ""))))
        with self._trava:
            if self.fase not in ("erro", "fim"):
                self.fase = "fim"

    def enviar(self, **comando) -> None:
        try:
            self.proc.stdin.write(json.dumps(comando) + "\n")
            self.proc.stdin.flush()
        except (OSError, ValueError):
            pass  # o processo já terminou

    def pegar_historico(self) -> Optional[List[int]]:
        with self._trava:
            historico, self._historico = self._historico, None
        return historico

    def pegar_numeros(self) -> List[int]:
        numeros = []
        while True:
            try:
                numeros.append(self._numeros.get_nowait())
            except queue.Empty:
                return numeros

    def ativo(self) -> bool:
        return self.proc.poll() is None

    def parar(self) -> None:
        self.enviar(cmd="parar")
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.terminate()


CONFIG_PAINEL_PADRAO = {"url": "", "escondido": False, "auto_confirmar": True, "iniciar_sozinho": False,
                        "bacbo_padroes_desligados": [], "bacbo_padroes_extras": "",
                        "bacbo_url": "", "bacbo_escondido": False, "bacbo_auto_confirmar": True}


def _arquivo_config_painel() -> str:
    return os.path.join(_pasta_do_robo(), "painel_robo_config.json")


def ler_config_painel() -> dict:
    """Escolhas do modo automático guardadas no PC (endereço da mesa, modo escondido...)."""
    try:
        with open(_arquivo_config_painel(), encoding="utf-8") as arq:
            dados = json.load(arq)
        return {**CONFIG_PAINEL_PADRAO, **(dados if isinstance(dados, dict) else {})}
    except (OSError, ValueError):
        return dict(CONFIG_PAINEL_PADRAO)


def salvar_config_painel(dados: dict) -> None:
    """Grava só as chaves recebidas e mantém as outras (ex.: salvar a mesa não apaga os padrões do Bac Bo)."""
    try:
        atual = ler_config_painel()
        with open(_arquivo_config_painel(), "w", encoding="utf-8") as arq:
            json.dump({**atual, **dados}, arq, ensure_ascii=False, indent=2)
    except OSError:
        pass  # sem permissão de escrita: o painel funciona, só não lembra das escolhas


class SessaoWeb:
    """Estado único do painel. Fica guardado pelo Streamlit e sobrevive a recarregar a página."""

    def __init__(self) -> None:
        self.trava = threading.RLock()
        self.config = Config()
        self.motor = MotorWeb(self.config)
        self.modo: Optional[str] = None
        self.leitor: Optional[LeitorProcesso] = None
        self.sim = {"rodando": False, "rng": None, "proximo": 0.0, "rapido": False}
        self.backtest: Optional[dict] = None
        self.aviso: Optional[str] = None
        self.auto_iniciado = False  # "Começar a ler quando o painel abrir" já foi feito?
        self.bacbo = None  # SessaoBacBo, criada na primeira vez que o Bac Bo é aberto

    # --- sessão e modo -------------------------------------------------------------
    def nova_sessao(self, config: Config) -> None:
        with self.trava:
            self.config = config
            self.motor = MotorWeb(config)

    def trocar_modo(self, modo: str) -> None:
        with self.trava:
            if modo != self.modo:
                self.parar_leitor()
                self.sim["rodando"] = False
                if getattr(self, "bacbo", None) is not None:
                    self.bacbo.sim["rodando"] = False
                self.modo = modo

    # --- leitura automática --------------------------------------------------------
    def iniciar_leitor(self, url: Optional[str], escondido: bool = False, auto_confirmar: bool = False) -> None:
        with self.trava:
            self.parar_leitor()
            self.leitor = LeitorProcesso(url or None, escondido=escondido, auto_confirmar=auto_confirmar)

    def parar_leitor(self) -> None:
        with self.trava:
            if self.leitor is not None:
                self.leitor.parar()
                self.leitor = None
            if getattr(self, "bacbo", None) is not None:
                self.bacbo.parar_leitor()

    def leitor_ativo(self) -> bool:
        return self.leitor is not None and self.leitor.ativo()

    # --- simulador -----------------------------------------------------------------
    def iniciar_sim(self, rapido: bool, semente: Optional[int]) -> None:
        with self.trava:
            rng = random.Random(semente)
            self.sim.update(rodando=True, rng=rng, rapido=rapido)
            self.sim["proximo"] = time.time() + self._intervalo_sim()

    def _intervalo_sim(self) -> float:
        # Mesma ordem de sorteio do ColetorSimulado: primeiro o intervalo, depois o número
        return 1.0 if self.sim["rapido"] else self.sim["rng"].uniform(10.0, 15.0)

    # --- a cada atualização da tela ------------------------------------------------
    def tick(self) -> None:
        with self.trava:
            if self.leitor is not None:
                historico = self.leitor.pegar_historico()
                if historico and self.motor.total_giros == 0 and not self.motor.historico:
                    self.motor.carregar_historico(historico)
                elif historico:
                    # A faixa foi confirmada de novo no meio da sessão: os números que saíram
                    # nesse intervalo são achados pela mesma "emenda" do leitor e processados.
                    anterior = [g.numero for g in reversed(self.motor.historico)]
                    atual = list(reversed(historico))
                    for numero in reversed(ColetorNavegador.calcular_novos(anterior, atual) or []):
                        self.motor.processar(numero)
                for numero in self.leitor.pegar_numeros():
                    self.motor.processar(numero)
            if self.sim["rodando"]:
                agora, feitos = time.time(), 0
                while agora >= self.sim["proximo"] and feitos < 30:
                    self.motor.processar(self.sim["rng"].randint(0, 36))
                    self.sim["proximo"] += self._intervalo_sim()
                    feitos += 1


class Html:
    """Pedaços visuais do painel. Tudo em uma linha, para o Markdown do Streamlit não mexer."""

    CORES = {"bg": "#0b0d12", "surface": "#131720", "surface2": "#1a1f2b", "line": "#262c3a",
             "ink": "#eef0f4", "ink2": "#aab1be", "muted": "#7d8594", "red": "#ff2d4b",
             "black": "#16181e", "green": "#14d27a", "blue": "#3d8bff", "gold": "#e8b84a",
             "good": "#2fd17a", "bad": "#ff4d5e", "player": "#2f6fff"}

    @classmethod
    def css(cls) -> str:
        c = cls.CORES
        regras = [
            "@import url('https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,600;12..96,800&family=JetBrains+Mono:wght@400;600;700&display=swap');",
            f":root{{--rr-bg:{c['bg']};--rr-surface:{c['surface']};--rr-surface2:{c['surface2']};--rr-line:{c['line']};"
            f"--rr-ink:{c['ink']};--rr-ink2:{c['ink2']};--rr-muted:{c['muted']};--rr-red:{c['red']};--rr-black:{c['black']};"
            f"--rr-green:{c['green']};--rr-blue:{c['blue']};--rr-gold:{c['gold']};--rr-good:{c['good']};--rr-bad:{c['bad']};"
            "--rr-display:'Bricolage Grotesque','Segoe UI',system-ui,sans-serif;--rr-mono:'JetBrains Mono',ui-monospace,Consolas,monospace;}",
            # força o escuro mesmo se o Streamlit estiver no tema claro
            ".stApp,[data-testid='stAppViewContainer']{background:radial-gradient(1200px 600px at 75% -10%,rgba(255,45,75,.07),transparent 60%),var(--rr-bg)!important;color:var(--rr-ink);}",
            "[data-testid='stHeader']{background:transparent!important;}",
            "[data-testid='stSidebar']{background:#0f1218!important;border-right:1px solid var(--rr-line);}",
            "[data-testid='stSidebar'] *,.stApp label,.stApp p,.stApp span,.stApp li{color:var(--rr-ink);}",
            ".stApp [data-testid='stCaptionContainer'] *,.stApp small{color:var(--rr-muted)!important;}",
            ".block-container{padding-top:1.6rem;max-width:1320px;}",
            ".stApp input,.stApp textarea{background:var(--rr-surface2)!important;color:var(--rr-ink)!important;}",
            ".stApp [data-baseweb='input']>div,.stApp [data-baseweb='base-input']{background:var(--rr-surface2)!important;border-color:var(--rr-line)!important;}",
            ".stApp .stButton>button{background:var(--rr-surface2);color:var(--rr-ink);border:1px solid var(--rr-line);border-radius:10px;font-family:var(--rr-mono);font-weight:600;}",
            ".stApp .stButton>button:hover{border-color:var(--rr-red);color:#fff;}",
            ".stApp .stButton>button[kind='primary']{background:var(--rr-red);border-color:var(--rr-red);color:#fff;box-shadow:0 0 18px rgba(255,45,75,.35);}",
            ".stApp [data-testid='stExpander']{background:var(--rr-surface);border:1px solid var(--rr-line);border-radius:12px;}",
            ".stApp [data-testid='stProgress'] div[role='progressbar']>div>div{background:var(--rr-red)!important;}",
            # cabeçalho
            ".rr-topo{display:flex;flex-wrap:wrap;align-items:flex-end;justify-content:space-between;gap:12px;margin-bottom:18px;}",
            ".rr-titulo{font-family:var(--rr-display);font-weight:800;font-size:2rem;letter-spacing:-.03em;line-height:1;margin:0;color:var(--rr-ink);}",
            ".rr-sub{font-family:var(--rr-mono);font-size:.72rem;letter-spacing:.12em;text-transform:uppercase;color:var(--rr-muted);margin-bottom:6px;}",
            ".rr-status{display:inline-flex;align-items:center;gap:8px;padding:6px 12px;border-radius:999px;border:1px solid var(--rr-line);background:var(--rr-surface);font-family:var(--rr-mono);font-size:.78rem;color:var(--rr-ink2);}",
            ".rr-status i{width:8px;height:8px;border-radius:50%;background:var(--rr-muted);display:inline-block;}",
            ".rr-status.on i{background:var(--rr-green);box-shadow:0 0 0 0 rgba(20,210,122,.6);animation:rr-ping 1.6s infinite;}",
            ".rr-status.alerta i{background:var(--rr-gold);}",
            "@keyframes rr-ping{0%{box-shadow:0 0 0 0 rgba(20,210,122,.55)}80%{box-shadow:0 0 0 8px rgba(20,210,122,0)}100%{box-shadow:0 0 0 0 rgba(20,210,122,0)}}",
            # cartões
            ".rr-cartoes{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px;margin:4px 0 18px;}",
            ".rr-cartao{background:linear-gradient(180deg,var(--rr-surface2),var(--rr-surface));border:1px solid var(--rr-line);border-radius:14px;padding:16px 18px;display:grid;gap:6px;min-width:0;}",
            ".rr-cartao .r{font-family:var(--rr-mono);font-size:.7rem;letter-spacing:.1em;text-transform:uppercase;color:var(--rr-muted);}",
            ".rr-cartao .v{font-family:var(--rr-display);font-weight:800;font-size:1.9rem;letter-spacing:-.02em;line-height:1.05;color:var(--rr-ink);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}",
            ".rr-cartao .d{font-family:var(--rr-mono);font-size:.76rem;color:var(--rr-ink2);}",
            ".rr-pos{color:var(--rr-good)!important;}.rr-neg{color:var(--rr-bad)!important;}",
            # pedras
            ".rr-bloco{background:var(--rr-surface);border:1px solid var(--rr-line);border-radius:14px;padding:16px 18px;margin-bottom:16px;}",
            ".rr-bloco .rr-h{font-family:var(--rr-display);font-weight:800;font-size:1rem;margin:0 0 12px;color:var(--rr-ink);letter-spacing:-.01em;}",
            ".rr-bloco .rr-h small{font-family:var(--rr-mono);font-weight:400;font-size:.7rem;color:var(--rr-muted);margin-left:8px;letter-spacing:.06em;text-transform:uppercase;}",
            ".rr-pedras{display:flex;flex-wrap:wrap;gap:8px;align-items:center;}",
            ".rr-pedra{width:40px;height:40px;border-radius:50%;display:inline-grid;place-items:center;flex:none;font-family:var(--rr-mono);font-weight:700;font-size:.92rem;color:#fff;}",
            ".rr-pedra.v{background:radial-gradient(circle at 35% 30%,#ff5a70,var(--rr-red) 60%);box-shadow:0 0 12px rgba(255,45,75,.55);}",
            ".rr-pedra.p{background:linear-gradient(160deg,#23262e,var(--rr-black));box-shadow:inset 0 0 0 1px #343a47;}",
            ".rr-pedra.z{background:radial-gradient(circle at 35% 30%,#4dffa6,var(--rr-green) 60%);box-shadow:0 0 14px rgba(20,210,122,.6);color:#04140b;}",
            ".rr-pedra.pq{width:30px;height:30px;font-size:.78rem;}",
            ".rr-pedra.nova{width:52px;height:52px;font-size:1.15rem;outline:2px solid var(--rr-ink);outline-offset:3px;}",
            ".rr-pedras .rot{font-family:var(--rr-mono);font-size:.68rem;color:var(--rr-muted);letter-spacing:.08em;text-transform:uppercase;}",
            # alertas
            ".rr-alerta{position:relative;border-radius:16px;padding:20px 22px;margin-bottom:16px;background:linear-gradient(135deg,rgba(255,45,75,.12),rgba(19,23,32,.95) 45%);border:1px solid var(--rr-red);animation:rr-brilho 2.2s ease-in-out infinite;}",
            "@keyframes rr-brilho{0%,100%{box-shadow:0 0 0 1px rgba(255,45,75,.6),0 0 22px rgba(255,45,75,.25)}50%{box-shadow:0 0 0 1px rgba(255,45,75,.9),0 0 38px rgba(255,45,75,.5)}}",
            ".rr-alerta .tag{font-family:var(--rr-mono);font-size:.72rem;letter-spacing:.14em;text-transform:uppercase;color:var(--rr-red);font-weight:700;}",
            ".rr-alerta .pad{font-family:var(--rr-display);font-weight:800;font-size:1.25rem;margin:4px 0 12px;color:var(--rr-ink);}",
            ".rr-alerta .grade{display:grid;grid-template-columns:minmax(0,1.4fr) minmax(0,1fr) minmax(0,1fr);gap:16px;align-items:start;}",
            ".rr-alerta .lbl{font-family:var(--rr-mono);font-size:.68rem;letter-spacing:.1em;text-transform:uppercase;color:var(--rr-muted);margin-bottom:6px;}",
            ".rr-alvos{display:flex;flex-wrap:wrap;gap:8px;}",
            ".rr-alvo{display:inline-flex;align-items:center;gap:10px;padding:10px 14px;border-radius:12px;background:var(--rr-surface2);border:1px solid var(--rr-line);font-family:var(--rr-display);font-weight:800;font-size:1.15rem;color:var(--rr-ink);}",
            ".rr-alvo small{font-family:var(--rr-mono);font-weight:400;font-size:.72rem;color:var(--rr-ink2);}",
            ".rr-alvo .sw{width:22px;height:22px;border-radius:50%;display:inline-block;}",
            ".rr-valor{font-family:var(--rr-display);font-weight:800;font-size:1.5rem;color:var(--rr-ink);}",
            ".rr-valor small{display:block;font-family:var(--rr-mono);font-weight:400;font-size:.74rem;color:var(--rr-ink2);margin-top:2px;}",
            ".rr-validade{margin-top:14px;font-family:var(--rr-mono);font-size:.74rem;color:var(--rr-ink2);}",
            ".rr-calmo{border-radius:16px;padding:18px 22px;margin-bottom:16px;background:var(--rr-surface);border:1px dashed var(--rr-line);display:flex;align-items:center;gap:16px;flex-wrap:wrap;}",
            ".rr-calmo b{font-family:var(--rr-display);font-size:1.05rem;color:var(--rr-ink);}",
            ".rr-calmo span{font-family:var(--rr-mono);font-size:.78rem;color:var(--rr-ink2);}",
            # feed e tabela
            ".rr-feed{display:grid;gap:6px;}",
            ".rr-item{display:grid;grid-template-columns:auto minmax(0,1fr) auto;gap:12px;align-items:center;padding:8px 10px;border-radius:10px;background:var(--rr-surface2);}",
            ".rr-badge{font-family:var(--rr-mono);font-size:.7rem;font-weight:700;letter-spacing:.06em;padding:4px 8px;border-radius:6px;white-space:nowrap;}",
            ".rr-badge.g{background:rgba(47,209,122,.14);color:var(--rr-good);}.rr-badge.l{background:rgba(255,77,94,.14);color:var(--rr-bad);}.rr-badge.z{background:rgba(232,184,74,.14);color:var(--rr-gold);}",
            ".rr-item .t{font-size:.86rem;color:var(--rr-ink2);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}",
            ".rr-item .x{font-family:var(--rr-mono);font-size:.82rem;font-weight:600;}",
            ".rr-tabela{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums;}",
            ".rr-tabela th{font-family:var(--rr-mono);font-size:.66rem;letter-spacing:.08em;text-transform:uppercase;color:var(--rr-muted);text-align:right;padding:8px 6px;border-bottom:1px solid var(--rr-line);font-weight:600;}",
            ".rr-tabela td{text-align:right;padding:9px 6px;border-bottom:1px solid var(--rr-line);font-family:var(--rr-mono);font-size:.84rem;color:var(--rr-ink);}",
            ".rr-tabela th:first-child,.rr-tabela td:first-child{text-align:left;}",
            ".rr-nota{font-size:.82rem;color:var(--rr-muted);margin-top:10px;line-height:1.5;}",
            ".rr-graf svg{width:100%;height:auto;display:block;}",
            ".rr-graf text{fill:var(--rr-muted);font-family:var(--rr-mono);font-size:12px;}",
            ".rr-legenda{display:flex;gap:16px;flex-wrap:wrap;font-family:var(--rr-mono);font-size:.74rem;color:var(--rr-ink2);margin-bottom:8px;}",
            ".rr-legenda i{display:inline-block;width:16px;height:3px;border-radius:2px;vertical-align:middle;margin-right:6px;}",
            ".rr-selo{display:inline-flex;align-items:center;gap:10px;padding:10px 14px;border-radius:12px;font-family:var(--rr-mono);font-size:.82rem;}",
            ".rr-selo.ok{background:rgba(47,209,122,.12);color:var(--rr-good);border:1px solid rgba(47,209,122,.35);}",
            ".rr-selo.nao{background:rgba(255,77,94,.12);color:var(--rr-bad);border:1px solid rgba(255,77,94,.35);}",
            ".rr-marca{font-family:var(--rr-display);font-weight:800;font-size:1.25rem;letter-spacing:-.02em;color:var(--rr-ink);display:flex;align-items:center;gap:10px;margin:4px 0 2px;}",
            ".rr-marca i{width:14px;height:14px;border-radius:50%;background:conic-gradient(var(--rr-red) 0 33%,var(--rr-black) 0 66%,var(--rr-green) 0);box-shadow:0 0 10px rgba(255,45,75,.5);display:inline-block;}",
            # Bac Bo: pedras azul (Player), vermelha (Banker) e dourada (Empate), com a soma vencedora
            ".bb-chip{width:40px;height:40px;border-radius:50%;display:inline-flex;flex-direction:column;align-items:center;justify-content:center;flex:none;font-family:var(--rr-mono);font-weight:700;font-size:.95rem;line-height:1;color:#fff;}",
            ".stApp .bb-chip small,.bb-chip small{font-size:.6rem;font-weight:600;opacity:.9;margin-top:2px;color:inherit!important;}",
            f".bb-chip.p{{background:radial-gradient(circle at 35% 30%,#7aa5ff,{c['player']} 60%);box-shadow:0 0 12px rgba(47,111,255,.5);}}",
            ".bb-chip.b{background:radial-gradient(circle at 35% 30%,#ff5a70,var(--rr-red) 60%);box-shadow:0 0 12px rgba(255,45,75,.5);}",
            ".bb-chip.e{background:radial-gradient(circle at 35% 30%,#ffe2a1,var(--rr-gold) 60%);box-shadow:0 0 12px rgba(232,184,74,.5);color:#1a1300;}",
            ".bb-chip.pq{width:30px;height:30px;font-size:.78rem;}.bb-chip.pq small{display:none;}",
            ".bb-chip.nova{width:52px;height:52px;font-size:1.15rem;outline:2px solid var(--rr-ink);outline-offset:3px;}",
            f".rr-marca.bb i{{background:conic-gradient({c['player']} 0 45%,var(--rr-red) 0 90%,var(--rr-gold) 0);box-shadow:0 0 10px rgba(47,111,255,.5);}}",
            ".st-key-bb_p button,.st-key-bb_b button,.st-key-bb_e button{width:100%;min-height:64px;border:0!important;}",
            ".st-key-bb_p button p,.st-key-bb_b button p,.st-key-bb_e button p{font-family:var(--rr-display)!important;font-weight:800!important;font-size:1.15rem!important;letter-spacing:.04em;color:#fff!important;}",
            f".st-key-bb_p button{{background:{c['player']}!important;}}.st-key-bb_b button{{background:var(--rr-red)!important;}}",
            ".st-key-bb_e button{background:var(--rr-gold)!important;}.st-key-bb_e button p{color:#1a1300!important;}",
            ".rr-aviso{font-family:var(--rr-mono);font-size:.78rem;color:var(--rr-gold);margin:-6px 0 14px;}",
            "@media (max-width:900px){.rr-cartoes{grid-template-columns:repeat(2,minmax(0,1fr));}.rr-alerta .grade{grid-template-columns:1fr;}}",
            "@media (max-width:520px){.rr-cartao{padding:14px;}.rr-cartao .v{font-size:1.3rem;white-space:normal;overflow:visible;}}",
            "@media (prefers-reduced-motion:reduce){.rr-alerta,.rr-status.on i{animation:none;}}",
        ]
        # tabuleiro do modo manual: cada botão com a cor do número (classe st-key-<key> do Streamlit)
        for n in range(37):
            cor = {"v": c["red"], "p": "#20232b", "z": "#0fb868"}[cls.tipo_cor(n)]
            regras.append(f".st-key-rr_num_{n} button{{background:{cor}!important;color:#fff!important;border:0!important;"
                          f"min-height:44px;font-family:var(--rr-mono);font-weight:700;}}")
        return "<style>" + "".join(regras) + "</style>"

    @staticmethod
    def tipo_cor(n: int) -> str:
        return "z" if n == 0 else ("v" if n in NUMEROS_VERMELHOS else "p")

    @classmethod
    def pedra(cls, n: int, extra: str = "") -> str:
        return f'<span class="rr-pedra {cls.tipo_cor(n)} {extra}" title="{n}">{n}</span>'

    @classmethod
    def faixa_pedras(cls, historico: Deque[Giro]) -> str:
        giros = list(historico)[::-1]  # mais recente primeiro
        if not giros:
            return ('<div class="rr-bloco"><div class="rr-h">Últimas pedras</div>'
                    '<span class="rr-nota">Nenhum giro ainda. Os números aparecem aqui assim que saírem.</span></div>')
        pedras = "".join(cls.pedra(g.numero, "nova" if i == 0 else "") for i, g in enumerate(giros))
        return (f'<div class="rr-bloco"><div class="rr-h">Últimas pedras<small>mais recente à esquerda</small></div>'
                f'<div class="rr-pedras">{pedras}</div></div>')

    @staticmethod
    def cartao(rotulo: str, valor: str, detalhe: str, classe_valor: str = "") -> str:
        return (f'<div class="rr-cartao"><span class="r">{html.escape(rotulo)}</span>'
                f'<span class="v {classe_valor}">{valor}</span><span class="d">{detalhe}</span></div>')

    @classmethod
    def cartoes(cls, motor: MotorWeb) -> str:
        banca, total = motor.banca, motor.banca.total()
        variacao = banca.saldo - motor.config.banca_inicial
        if total.sinais:
            teorico = sum(est.sinais * MATEMATICA[t]["chance_teorica"] for t, est in banca.estatisticas.items()) / total.sinais
            acerto_txt, acerto_det = formatar_pct(total.taxa_acerto), f"chance real dos alvos: {formatar_pct(teorico)}"
        else:
            acerto_txt, acerto_det = "—", "aparece depois do primeiro sinal"
        esperado = -total.apostado * VANTAGEM_DA_CASA
        return '<div class="rr-cartoes">' + "".join([
            cls.cartao("Banca fictícia", formatar_reais(banca.saldo),
                       f'<span class="{"rr-pos" if variacao >= 0 else "rr-neg"}">{formatar_reais(variacao, com_sinal=True)}</span>'
                       f" desde o início"),
            cls.cartao("Acerto geral", acerto_txt, acerto_det),
            cls.cartao("Sinais conferidos", formatar_inteiro(total.sinais),
                       f'<span class="rr-pos">{total.greens} GREEN</span> · <span class="rr-neg">{total.losses} LOSS</span>'
                       f" · {total.greens_protecao} no zero"),
            cls.cartao("Resultado vs. esperado", formatar_reais(total.lucro, com_sinal=True),
                       f"a matemática previa {formatar_reais(esperado, com_sinal=True)}",
                       "rr-pos" if total.lucro > 0 else ("rr-neg" if total.lucro < 0 else "")),
        ]) + "</div>"

    @classmethod
    def alvos(cls, sinal: Sinal) -> str:
        if sinal.tipo == "cor":
            cor = sinal.alvos[0]
            amostra = "var(--rr-red)" if cor == VERMELHO else "#20232b;box-shadow:inset 0 0 0 1px #3a404d"
            return f'<span class="rr-alvo"><span class="sw" style="background:{amostra}"></span>{cor}</span>'
        if sinal.tipo == "duzia":
            return "".join(f'<span class="rr-alvo">{d}ª dúzia<small>{FAIXA_DUZIA[d]}</small></span>' for d in sinal.alvos)
        linha_na_mesa = {3: "linha de cima", 2: "linha do meio", 1: "linha de baixo"}
        return "".join(f'<span class="rr-alvo">Coluna {k}<small>{linha_na_mesa[k]} na mesa</small></span>' for k in sinal.alvos)

    @classmethod
    def alerta(cls, sinal: Sinal, motor: MotorWeb) -> str:
        cfg = motor.config
        n = {"cor": cfg.gatilho_cor, "duzia": cfg.gatilho_duzia, "coluna": cfg.gatilho_coluna}[sinal.tipo]
        gatilho = "".join(cls.pedra(g.numero, "pq") for g in list(motor.historico)[-n:])
        total = cfg.valor_por_alvo * len(sinal.alvos)
        if cfg.protecao_zero:
            protecao = (f'<div class="rr-valor" style="display:flex;align-items:center;gap:10px">{cls.pedra(0, "pq")}'
                        f'{formatar_reais(cfg.valor_protecao_zero)}<small style="display:inline">no zero</small></div>')
        else:
            protecao = '<div class="rr-valor" style="font-size:1rem">Sem proteção</div>'
        return (f'<div class="rr-alerta"><div class="tag">Gatilho ativado</div>'
                f'<div class="pad">{html.escape(sinal.padrao)}</div>'
                f'<div class="grade">'
                f'<div><div class="lbl">Alvo da entrada</div><div class="rr-alvos">{cls.alvos(sinal)}</div>'
                f'<div class="lbl" style="margin-top:14px">Sequência que disparou</div><div class="rr-pedras">{gatilho}</div></div>'
                f'<div><div class="lbl">Valor sugerido</div><div class="rr-valor">{formatar_reais(cfg.valor_por_alvo)}'
                f'<small>em cada alvo · {formatar_reais(total)} no total</small></div></div>'
                f'<div><div class="lbl">Proteção</div>{protecao}</div>'
                f'</div><div class="rr-validade">Vale só para o próximo giro. O painel confere sozinho e lança na banca fictícia.</div></div>')

    @classmethod
    def sem_alerta(cls, motor: MotorWeb) -> str:
        ultimo = cls.pedra(motor.historico[-1].numero, "pq") if motor.historico else ""
        return (f'<div class="rr-calmo">{ultimo}<div><b>Nenhum gatilho ativo</b><br>'
                f'<span>Cor: 4 iguais seguidas · Dúzia ou coluna: 3 seguidas no mesmo grupo</span></div></div>')

    @classmethod
    def feed(cls, motor: MotorWeb, limite: int = 10) -> str:
        itens = list(motor.resultados)[-limite:][::-1]
        if not itens:
            return '<div class="rr-bloco"><div class="rr-h">Últimas entradas</div><span class="rr-nota">Os sinais conferidos aparecem aqui.</span></div>'
        linhas = []
        for r in itens:
            classe = "g" if r.status == "GREEN" else ("z" if r.giro.numero == 0 and r.status != "LOSS" else "l")
            rotulo = {"g": "GREEN", "l": "LOSS", "z": "ZERO"}[classe]
            linhas.append(f'<div class="rr-item"><span class="rr-badge {classe}">{rotulo}</span>'
                          f'<span class="t">{html.escape(NOMES_CURTOS[r.sinal.tipo])} · saiu {r.giro.numero}</span>'
                          f'<span class="x {"rr-pos" if r.lucro > 0 else "rr-neg"}">{formatar_reais(r.lucro, com_sinal=True)}</span></div>')
        return f'<div class="rr-bloco"><div class="rr-h">Últimas entradas</div><div class="rr-feed">{"".join(linhas)}</div></div>'

    @staticmethod
    def tabela_padroes(banca: BancaFicticia, titulo: str = "Desempenho por padrão") -> str:
        linhas = []
        for tipo, est in banca.estatisticas.items():
            mat = MATEMATICA[tipo]
            acerto = formatar_pct(est.taxa_acerto) if est.sinais else "—"
            linhas.append(f"<tr><td>{NOMES_CURTOS[tipo]}</td><td>{formatar_inteiro(est.sinais)}</td><td>{acerto}</td>"
                          f"<td>{formatar_pct(mat['chance_teorica'])}</td><td>{formatar_pct(mat['acerto_minimo'])}</td>"
                          f'<td class="{"rr-pos" if est.lucro > 0 else ("rr-neg" if est.lucro < 0 else "")}">'
                          f"{formatar_reais(est.lucro, com_sinal=True)}</td></tr>")
        return (f'<div class="rr-bloco"><div class="rr-h">{titulo}</div><table class="rr-tabela"><thead><tr><th>Padrão</th><th>Sinais</th>'
                f"<th>Acerto</th><th>Chance real</th><th>Para empatar</th><th>Resultado</th></tr></thead>"
                f'<tbody>{"".join(linhas)}</tbody></table>'
                f'<div class="rr-nota">Acerto é quantas vezes o alvo saiu. Chance real é a probabilidade do alvo em qualquer giro. '
                f"Com poucos sinais o acerto oscila muito; com muitos, ele encosta na chance real.</div></div>")

    @staticmethod
    def grafico_curva(curva: List[Tuple[int, float, float]], titulo: str, rotulo_x: str = "giros",
                      previsto: str = "Previsto pela matemática (−1/37 do apostado)") -> str:
        if len(curva) < 2:
            return (f'<div class="rr-bloco"><div class="rr-h">{titulo}</div>'
                    '<span class="rr-nota">O gráfico aparece depois do primeiro sinal conferido.</span></div>')
        W, H, ml, mr, mt, mb = 960, 300, 86, 16, 14, 34
        xs = [p[0] for p in curva]
        ys = [v for p in curva for v in (p[1], p[2])]
        x0, x1 = min(xs), max(xs) if max(xs) > min(xs) else min(xs) + 1
        menor, maior = min(ys + [0.0]), max(ys + [0.0])
        # passo "redondo" para as marcas do eixo Y
        bruto = max(1.0, (maior - menor) / 5)
        base = 10 ** int(f"{bruto:e}".split("e")[1])
        passo = next(m * base for m in (1, 2, 2.5, 5, 10) if m * base >= bruto)
        y_min = (menor // passo) * passo
        y_max = -((-maior) // passo) * passo
        if y_max == y_min:
            y_max = y_min + passo
        sx = lambda v: ml + (v - x0) / (x1 - x0) * (W - ml - mr)
        sy = lambda v: mt + (y_max - v) / (y_max - y_min) * (H - mt - mb)
        partes = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{html.escape(titulo)}">']
        v = y_min
        while v <= y_max + 1e-9:
            cor = "#3a4150" if abs(v) < 1e-9 else "#1f2430"
            rot = formatar_reais(v).replace(",00", "")
            partes.append(f'<line x1="{ml}" x2="{W - mr}" y1="{sy(v):.1f}" y2="{sy(v):.1f}" stroke="{cor}" stroke-width="1"/>'
                          f'<text x="{ml - 10}" y="{sy(v) + 4:.1f}" text-anchor="end">{rot}</text>')
            v += passo
        for i, xv in enumerate((x0, (x0 + x1) / 2, x1)):
            ancora = ("start", "middle", "end")[i]
            partes.append(f'<text x="{sx(xv):.1f}" y="{H - 10}" text-anchor="{ancora}">'
                          f'{formatar_inteiro(int(round(xv)))}{" " + rotulo_x if i == 2 else ""}</text>')
        for idx, cor in ((2, "#8b93a3"), (1, Html.CORES["blue"])):
            pts = " ".join(f"{sx(p[0]):.1f},{sy(p[idx]):.1f}" for p in curva)
            partes.append(f'<polyline points="{pts}" fill="none" stroke="{cor}" stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round"/>')
            ult = curva[-1]
            partes.append(f'<circle cx="{sx(ult[0]):.1f}" cy="{sy(ult[idx]):.1f}" r="5" fill="{cor}" stroke="{Html.CORES["surface"]}" stroke-width="2"/>')
        partes.append("</svg>")
        legenda = (f'<div class="rr-legenda"><span><i style="background:{Html.CORES["blue"]}"></i>Banca fictícia (resultado acumulado)</span>'
                   f'<span><i style="background:#8b93a3"></i>{html.escape(previsto)}</span></div>')
        return f'<div class="rr-bloco rr-graf"><div class="rr-h">{titulo}</div>{legenda}{"".join(partes)}</div>'


MODO_AUTO, MODO_MANUAL = "Mesa real (automática)", "Mesa real (manual)"
MODO_SIM, MODO_BACKTEST = "Simulador ao vivo", "Backtest em massa"


def app_web() -> None:
    """A tela do painel. O Streamlit executa esta função de novo a cada interação."""
    import streamlit as st

    st.set_page_config(page_title="Robô de Roleta", page_icon="🎯", layout="wide",
                       initial_sidebar_state="expanded")
    st.markdown(Html.css(), unsafe_allow_html=True)
    if not hasattr(st, "fragment"):
        st.error("Este painel precisa do Streamlit 1.37 ou mais novo. Rode:  py -m pip install -U streamlit")
        st.stop()

    # No seu PC (aberto pelo atalho/opção 6) existe UM painel só, que continua vivo se você
    # recarregar a página. Hospedado na internet, cada visitante ganha o próprio painel.
    no_meu_pc = os.environ.get("ROBO_ROLETA_LOCAL") == "1"

    @st.cache_resource
    def obter_sessao() -> SessaoWeb:
        return SessaoWeb()

    if no_meu_pc:
        sessao = obter_sessao()
    else:
        if "rr_sessao" not in st.session_state:
            st.session_state["rr_sessao"] = SessaoWeb()
        sessao = st.session_state["rr_sessao"]

    # --------------------------- barra lateral -------------------------------------
    with st.sidebar:
        marca = st.container()  # a marca fica no topo, mas depende do jogo escolhido logo abaixo
        jogo = st.radio("Jogo", [JOGO_ROLETA, JOGO_BACBO], key="rr_jogo", horizontal=True)
        e_bacbo = jogo == JOGO_BACBO
        marca.markdown(f'<div class="rr-marca{" bb" if e_bacbo else ""}"><i></i>'
                       f'{"Robô de Bac Bo" if e_bacbo else "Robô de Roleta"}</div>'
                       f'<div class="rr-sub">{"Bac Bo (Evolution)" if e_bacbo else "Roleta europeia"} · banca fictícia</div>',
                       unsafe_allow_html=True)
        # No PC abre na mesa automática; hospedado, abre no backtest (o que funciona online)
        modo = st.radio("Modo de operação", [MODO_AUTO, MODO_MANUAL, MODO_SIM, MODO_BACKTEST],
                        index=0 if no_meu_pc else 3, key="rr_modo")
        bacbo = obter_bacbo(sessao, no_meu_pc) if e_bacbo else None
        if bacbo is not None:
            ajustes, config_tela, mudou = _ajustes_bacbo(st, bacbo)
            _padroes_bacbo(st, bacbo)
        else:
            with st.expander("Ajustes da banca fictícia"):
                valor = st.number_input("Valor por alvo (R$)", min_value=1.0, max_value=100000.0, value=10.0, step=1.0, key="rr_valor")
                cobrir_zero = st.checkbox("Cobrir o zero", value=True, key="rr_zero_on")
                valor_zero = st.number_input("Valor no zero (R$)", min_value=0.0, max_value=100000.0, value=1.0, step=0.5, key="rr_zero_valor")
                banca_ini = st.number_input("Banca inicial (R$)", min_value=1.0, max_value=10_000_000.0, value=1000.0, step=100.0, key="rr_banca")
                st.caption("Os valores padrão são os dos testes de aceitação.")
            ajustes = dict(valor_por_alvo=float(valor), protecao_zero=bool(cobrir_zero),
                           valor_protecao_zero=float(valor_zero), banca_inicial=float(banca_ini))
            try:
                config_tela = Config(**ajustes)
            except ValueError as erro:
                st.error(f"Ajuste inválido: {erro}")
                config_tela = Config()
            mudou = any(getattr(sessao.config, k) != v for k, v in ajustes.items())
        if modo != MODO_BACKTEST:
            if mudou:
                st.caption("Os ajustes novos valem a partir de uma nova sessão.")
            if st.button("Nova sessão", key="rr_nova", type="primary" if mudou else "secondary"):
                if bacbo is not None:
                    bacbo.nova_sessao(config_tela)
                else:
                    sessao.nova_sessao(config_tela)
        st.markdown('<div class="rr-nota">O robô só observa. Nenhuma aposta é feita: '
                    'todos os valores são de uma banca fictícia.</div>', unsafe_allow_html=True)
        # Só no seu PC: hospedado, um visitante não pode desligar o site nem trocar o código
        atualizar = no_meu_pc and st.button("Atualizar robô", key="rr_atualizar")
        desligar = no_meu_pc and st.button("Desligar o painel", key="rr_desligar")

    if atualizar:
        with st.spinner("Baixando a versão mais nova do GitHub..."):
            ok, trocou, mensagem = atualizar_robo()
        if trocou:
            # Para tudo e limpa o estado guardado: na próxima execução o Streamlit já lê o
            # arquivo novo, e o painel recomeça com o código atualizado.
            sessao.parar_leitor()
            sessao.sim["rodando"] = False
            st.cache_resource.clear()
            st.success(mensagem + " Recarregando o painel...")
            time.sleep(1.5)
            st.rerun()
        elif ok:
            st.info(mensagem)
        else:
            st.error(mensagem)

    if desligar:
        # O painel roda escondido; este botão é o jeito de desligá-lo.
        sessao.parar_leitor()
        sessao.sim["rodando"] = False
        try:
            os.remove(_arquivo_porta())
        except OSError:
            pass
        st.markdown('<div class="rr-calmo"><div><b>Painel desligado.</b><br><span>Pode fechar esta aba. '
                    'Para abrir de novo, use o atalho da Área de Trabalho ou a opção 6 do menu.</span></div></div>',
                    unsafe_allow_html=True)
        threading.Timer(1.5, lambda: os._exit(0)).start()  # dá tempo da mensagem chegar ao navegador
        st.stop()

    # Trocar de jogo conta como trocar de modo: pausa a leitura e o simulador (as sessões ficam guardadas)
    sessao.trocar_modo(f"{jogo} · {modo}")

    if bacbo is not None:
        app_bacbo(st, bacbo, modo, no_meu_pc, config_tela)
        return

    tem_playwright = importlib.util.find_spec("playwright") is not None

    # "Começar a ler quando o painel abrir": liga a leitura sozinho, uma vez, com as escolhas salvas
    if no_meu_pc and modo == MODO_AUTO and tem_playwright and not sessao.auto_iniciado:
        sessao.auto_iniciado = True
        cfg = ler_config_painel()
        if cfg["iniciar_sozinho"] and cfg["url"] and sessao.leitor is None:
            sessao.iniciar_leitor(cfg["url"], escondido=cfg["escondido"], auto_confirmar=cfg["auto_confirmar"])

    # --------------------------- cabeçalho -----------------------------------------
    def cabecalho() -> None:
        """Título e status. Nos modos ao vivo ele roda dentro do fragmento e se atualiza sozinho."""
        if modo == MODO_AUTO and not tem_playwright:
            status = ("Só no computador", "alerta")  # hospedado: não existe Chrome para ler a mesa
        elif modo == MODO_AUTO:
            fase = sessao.leitor.fase if sessao.leitor else None
            status = {"iniciando": ("Conectando ao Chrome", "alerta"), "conectando": ("Conectando ao Chrome", "alerta"),
                      "procurando": ("Procurando a faixa", "alerta"), "lendo": ("Lendo a mesa ao vivo", "on"),
                      "erro": ("Erro na leitura", ""), "fim": ("Leitura encerrada", "")}.get(fase, ("Parado", ""))
        elif modo == MODO_SIM:
            status = ("Simulando", "on") if sessao.sim["rodando"] else ("Pausado", "")
        elif modo == MODO_MANUAL:
            status = ("Aguardando o próximo número", "on")
        else:
            status = ("Backtest", "")
        st.markdown(f'<div class="rr-topo"><div><div class="rr-sub">{html.escape(modo)}</div>'
                    f'<div class="rr-titulo" role="heading" aria-level="1">Painel de sinais</div></div>'
                    f'<span class="rr-status {status[1]}"><i></i>{status[0]}</span></div>', unsafe_allow_html=True)

    if modo == MODO_BACKTEST:
        cabecalho()
        demonstracao = None
        if not no_meu_pc:
            # Hospedado: o backtest de aceitação roda UMA vez no servidor e fica pronto para
            # todos os visitantes (quem abrir o link já vê o resultado, sem esperar).
            @st.cache_resource(show_spinner="Rodando o backtest de 1.000.000 de giros (só na primeira visita)...")
            def backtest_demonstracao() -> dict:
                inicio = time.time()
                motor = executar_backtest(1_000_000, 42)
                return {"giros": 1_000_000, "semente": 42, "motor": motor,
                        "segundos": time.time() - inicio, "padrao": True}
            demonstracao = backtest_demonstracao
        _tela_backtest(st, sessao, ajustes, demonstracao)
        return

    # O modo manual tem status fixo: cabeçalho e tabuleiro ficam fora do fragmento
    if modo == MODO_MANUAL:
        cabecalho()
        _tela_manual(st, sessao)

    # --------------------------- painel ao vivo (atualiza sozinho) ------------------
    ao_vivo = sessao.leitor_ativo() or sessao.sim["rodando"]

    def painel_ao_vivo() -> None:
        sessao.tick()
        if modo in (MODO_AUTO, MODO_SIM):
            # Cabeçalho e controles dentro do fragmento: o status acompanha a leitura em tempo real
            cabecalho()
            if modo == MODO_AUTO:
                _controles_auto(st, sessao, tem_playwright)
            else:
                _controles_sim(st, sessao)
        if modo == MODO_AUTO and tem_playwright:
            _calibracao(st, sessao)
        motor = sessao.motor
        st.markdown(Html.cartoes(motor), unsafe_allow_html=True)
        st.markdown(Html.faixa_pedras(motor.historico), unsafe_allow_html=True)
        if motor.pendentes:
            st.markdown("".join(Html.alerta(s, motor) for s in motor.pendentes), unsafe_allow_html=True)
        else:
            st.markdown(Html.sem_alerta(motor), unsafe_allow_html=True)
        esquerda, direita = st.columns([1, 1.4])
        esquerda.markdown(Html.feed(motor), unsafe_allow_html=True)
        direita.markdown(Html.tabela_padroes(motor.banca), unsafe_allow_html=True)
        st.markdown(Html.grafico_curva(motor.curva, "Banca da sessão"), unsafe_allow_html=True)

    # O fragmento redesenha só esta parte a cada 1 s enquanto há leitura ou simulação,
    # sem recarregar a página inteira (a leitura em si acontece no processo separado).
    st.fragment(painel_ao_vivo, run_every=1.0 if ao_vivo else None)()


def _controles_auto(st, sessao, tem_playwright: bool, bacbo: bool = False) -> None:
    """
    Botões do modo automático. Durante a leitura só aparece 'Parar' (evita reiniciar sem querer).
    'sessao' é a SessaoWeb (roleta) ou a SessaoBacBo: as duas têm leitor, iniciar_leitor e parar_leitor.
    """
    if not tem_playwright:
        # Hospedado na internet (ou sem Playwright instalado) não existe o seu Chrome para ler
        st.info("A leitura automática da mesa funciona só com o robô rodando no seu computador, "
                "porque ela usa o seu Chrome. Instale com  py -m pip install playwright  e abra o painel "
                "pelo atalho. Aqui você pode usar o modo manual, o simulador e o backtest.")
        return
    k = "bb" if bacbo else "rr"          # prefixo das chaves dos botões
    c_ = "bacbo_" if bacbo else ""       # prefixo das escolhas salvas no arquivo de configuração
    if sessao.leitor_ativo():
        c1, c2 = st.columns([4, 1])
        jeito = "Chrome escondido" if sessao.leitor.escondido else "Chrome com janela"
        c1.caption(f"Leitura ligada ({jeito}). Para trocar de mesa ou de modo, pare a leitura e inicie de novo.")
        if c2.button("Parar leitura", key=f"{k}_par_leitor"):
            sessao.parar_leitor()
            st.rerun()  # recarrega a página inteira para desligar a atualização automática
        return

    cfg = ler_config_painel()
    exemplo = "bac-bo-by-evolution" if bacbo else "immersive-roulette-by-evolution"
    c1, c2 = st.columns([3, 2])
    url = c1.text_input("Endereço da mesa", value=cfg[c_ + "url"], key=f"{k}_url",
                        placeholder=f"ex.: https://site-do-cassino/game/{exemplo}")
    janela = c2.radio("Chrome do robô", ["Escondido (sem janela)", "Visível (para fazer login)"],
                      index=0 if cfg[c_ + "escondido"] else 1, key=f"{k}_janela")
    c3, c4, c5 = st.columns([2, 2, 1])
    auto = c3.checkbox("Confirmar a faixa sozinho", value=cfg[c_ + "auto_confirmar"], key=f"{k}_auto")
    sozinho = False if bacbo else c4.checkbox("Começar a ler quando o painel abrir",
                                              value=cfg["iniciar_sozinho"], key="rr_sozinho")
    if c5.button("Iniciar leitura", key=f"{k}_ini_leitor", type="primary"):
        escondido = janela.startswith("Escondido")
        if escondido and not url.strip():
            st.error("No modo escondido o robô abre a mesa sozinho, então ele precisa do endereço dela. "
                     "Abra a mesa uma vez no modo Visível, copie o endereço da barra e cole aqui.")
            return
        escolhas = {c_ + "url": url.strip(), c_ + "escondido": escondido, c_ + "auto_confirmar": bool(auto)}
        if not bacbo:
            escolhas["iniciar_sozinho"] = bool(sozinho)
        salvar_config_painel(escolhas)
        sessao.iniciar_leitor(url.strip() or None, escondido=escondido, auto_confirmar=bool(auto))
        st.rerun()  # recarrega a página inteira para ligar a atualização automática
    mesa = "a mesa de Bac Bo" if bacbo else "a mesa"
    st.caption(f"Primeira vez (ou se o login expirar): escolha Visível, faça login na janela que abrir, abra {mesa} "
               "e copie o endereço da barra para cá. Depois, use Escondido: o robô entra na mesa sozinho, sem janela, "
               "e o Chrome dele fecha quando a leitura para.")


def _controles_sim(st, sessao: SessaoWeb) -> None:
    """Botões do simulador: mostra Iniciar ou Pausar conforme o estado."""
    c1, c2, c3 = st.columns([2, 2, 1])
    velocidade = c1.radio("Velocidade", ["Normal (10 a 15 s)", "Acelerado (1 s)"], key="rr_vel", horizontal=True)
    semente = c2.number_input("Semente (0 = aleatória)", min_value=0, max_value=10**9, value=0, step=1, key="rr_sem")
    if sessao.sim["rodando"]:
        if c3.button("Pausar", key="rr_pau_sim"):
            sessao.sim["rodando"] = False
            st.rerun()
    elif c3.button("Iniciar", key="rr_ini_sim", type="primary"):
        sessao.iniciar_sim(velocidade.startswith("Acelerado"), int(semente) or None)
        st.rerun()


def _calibracao(st, sessao, bacbo: bool = False) -> None:
    """Na tela: mostra a faixa encontrada para você confirmar (equivale ao Enter do terminal)."""
    leitor = sessao.leitor
    k = "bb" if bacbo else "rr"
    mesa = "a mesa de Bac Bo" if bacbo else "a Immersive Roulette"
    if leitor is None:
        st.info(f"Clique em **Iniciar leitura**. O robô abre (ou reaproveita) o Chrome dele; faça login, abra "
                f"{mesa} e a faixa de resultados aparece aqui para você confirmar.")
        return
    if leitor.fase == "erro":
        st.error(f"Não consegui ler a mesa: {leitor.erro}")
        return
    if leitor.fase == "fim":
        st.warning("A leitura foi encerrada (o Chrome do robô foi fechado?). Clique em Iniciar leitura para voltar.")
        return
    if leitor.fase in ("iniciando", "conectando"):
        st.info("Abrindo o Chrome do robô...")
        return
    if leitor.fase == "procurando":
        if not leitor.candidatas:
            st.info(f"Procurando a faixa de resultados... Abra {mesa} na janela do Chrome do robô.")
            if leitor.diagnostico:
                with st.expander("Diagnóstico (o que o robô está enxergando)"):
                    st.code("\n".join(leitor.diagnostico))
            return
        st.markdown('<div class="rr-sub" style="margin-top:6px">Faixa encontrada: confira com a mesa '
                    f'(o primeiro {"resultado" if bacbo else "número"} deve ser o último que saiu)</div>',
                    unsafe_allow_html=True)
        for i, itens in enumerate(leitor.candidatas):
            c1, c2, c3 = st.columns([5, 1, 1])
            if bacbo:
                desenho = "".join(HtmlBacBo.chip(RodadaBacBo.do_resultado(r, _soma_valida(soma)), "pq")
                                  for r, soma in itens)
            else:
                desenho = "".join(Html.pedra(n, "pq") for n in itens)
            c1.markdown(f'<div class="rr-pedras">{desenho}</div>', unsafe_allow_html=True)
            if c2.button("Confere", key=f"{k}_conf_{i}", type="primary"):
                leitor.enviar(cmd="confirmar", indice=i, invertida=False)
            # No Bac Bo a ordem vem da posição das bolinhas no quadro, então não existe "invertida"
            if not bacbo and c3.button("Invertida", key=f"rr_inv_{i}"):
                leitor.enviar(cmd="confirmar", indice=i, invertida=True)
        return
    if leitor.fase == "lendo":
        c1, c2 = st.columns([5, 1])
        if leitor.mensagens:
            hora, texto = leitor.mensagens[-1]
            c1.caption(f"Última mensagem do leitor ({hora}): {texto}")
        if c2.button("Procurar faixa de novo", key=f"{k}_procurar"):
            leitor.enviar(cmd="procurar")


def _tela_manual(st, sessao: SessaoWeb) -> None:
    """Tabuleiro clicável: clique no número que saiu na mesa."""
    with st.expander("Carregar os últimos números que a mesa já mostra"):
        c1, c2 = st.columns([4, 1])
        texto = c1.text_input("Do mais recente para o mais antigo, separados por espaço", key="rr_hist",
                              placeholder="ex.: 17 4 32 0 21")
        if c2.button("Carregar", key="rr_carregar"):
            try:
                numeros = [int(p) for p in texto.replace(",", " ").split()]
                if not numeros or any(not 0 <= n <= 36 for n in numeros):
                    raise ValueError
                with sessao.trava:
                    sessao.motor.carregar_historico(list(reversed(numeros)))
            except ValueError:
                st.error("Use só números de 0 a 36 separados por espaço.")

    st.markdown('<div class="rr-sub">Clique no número que saiu</div>', unsafe_allow_html=True)
    clicado: Optional[int] = None
    # Layout igual ao da mesa deitada: zero à esquerda, linhas de cima (3, 6, ... 36), do meio e de baixo
    for linha_mesa in (3, 2, 1):
        colunas = st.columns(13)
        if linha_mesa == 2 and colunas[0].button("0", key="rr_num_0"):
            clicado = 0
        for j in range(12):
            n = 3 * j + linha_mesa
            if colunas[j + 1].button(str(n), key=f"rr_num_{n}"):
                clicado = n
    c1, _ = st.columns([1, 5])
    if c1.button("Desfazer último", key="rr_desfazer"):
        with sessao.trava:
            if not sessao.motor.desfazer():
                st.warning("Nada para desfazer (dá para desfazer só o último número, uma vez).")
    if clicado is not None:
        with sessao.trava:
            sessao.motor.processar(clicado, permitir_desfazer=True)


def _tela_backtest(st, sessao: SessaoWeb, ajustes: dict, demonstracao=None) -> None:
    """Backtest em massa com barra de progresso e conferência do teste de aceitação."""
    c1, c2, c3 = st.columns([2, 2, 1])
    giros = c1.number_input("Giros", min_value=1000, max_value=5_000_000, value=1_000_000, step=100_000, key="rr_bt_giros")
    semente = c2.number_input("Semente", min_value=0, max_value=10**9, value=42, step=1, key="rr_bt_sem")
    if c3.button("Rodar backtest", key="rr_bt_rodar", type="primary"):
        barra = st.progress(0.0, text="Simulando...")
        inicio = time.time()
        config = Config(intervalo_min=0.0, intervalo_max=0.0, **ajustes)
        motor = executar_backtest(int(giros), int(semente), config,
                                  ao_progredir=lambda f: barra.progress(min(1.0, f), text=f"Simulando... {f * 100:.0f}%"))
        barra.empty()
        padrao = Config()  # o teste de aceitação só vale com os ajustes padrão
        sessao.backtest = {"giros": int(giros), "semente": int(semente), "motor": motor,
                           "segundos": time.time() - inicio,
                           "padrao": all(getattr(padrao, k) == v for k, v in ajustes.items())}

    resultado = sessao.backtest
    if not resultado and demonstracao is not None:
        resultado = demonstracao()  # versão hospedada: mostra o teste de aceitação já pronto
    if not resultado:
        st.markdown('<div class="rr-calmo"><div><b>Rode um backtest</b><br><span>1.000.000 de giros com semente 42 '
                    'é o teste de aceitação: tem que dar 195.368 sinais e −R$ 90.804,00.</span></div></div>',
                    unsafe_allow_html=True)
        return
    motor: MotorWeb = resultado["motor"]
    total = motor.banca.total()
    esperado = -total.apostado * VANTAGEM_DA_CASA
    st.markdown('<div class="rr-cartoes">' + "".join([
        Html.cartao("Giros simulados", formatar_inteiro(resultado["giros"]),
                    f'semente {resultado["semente"]} · {resultado["segundos"]:.1f} s'),
        Html.cartao("Sinais conferidos", formatar_inteiro(total.sinais),
                    f'<span class="rr-pos">{formatar_inteiro(total.greens)} GREEN</span> · '
                    f'<span class="rr-neg">{formatar_inteiro(total.losses)} LOSS</span>'),
        Html.cartao("Resultado real", formatar_reais(total.lucro, com_sinal=True),
                    (f"{total.lucro / total.apostado * 100:.2f}%".replace(".", ",") + " do total apostado")
                    if total.apostado else "nenhum sinal disparado",
                    "rr-pos" if total.lucro > 0 else "rr-neg"),
        Html.cartao("Esperado pela matemática", formatar_reais(esperado, com_sinal=True),
                    f"vantagem da casa de {formatar_pct(VANTAGEM_DA_CASA)}"),
    ]) + "</div>", unsafe_allow_html=True)
    if resultado["giros"] == 1_000_000 and resultado["semente"] == 42 and resultado["padrao"]:
        bateu = total.sinais == 195_368 and round(total.lucro, 2) == -90_804.0
        st.markdown(f'<div class="rr-selo {"ok" if bateu else "nao"}">'
                    f'{"Teste de aceitação: bateu" if bateu else "Teste de aceitação: NÃO bateu"} · '
                    f'{formatar_inteiro(total.sinais)} sinais · {formatar_reais(total.lucro, com_sinal=True)}</div>',
                    unsafe_allow_html=True)
    st.markdown(Html.grafico_curva(motor.curva, "Banca no backtest"), unsafe_allow_html=True)
    st.markdown(Html.tabela_padroes(motor.banca, "Desempenho por padrão no backtest"), unsafe_allow_html=True)


# ===================================================================================
# 11) BAC BO (Evolution)
# -----------------------------------------------------------------------------------
# Regras: 2 dados para o Player e 2 para o Banker; ganha a maior soma; somas iguais = empate.
# Pagamentos: Player e Banker pagam 1:1. No empate, quem apostou em Player ou Banker recebe
# 90% de volta. O empate paga conforme a soma: 2/12 = 88:1, 3/11 = 25:1, 4/10 = 10:1,
# 5/9 = 6:1 e 6/7/8 = 4:1.
# Matemática: Player e Banker ganham em 575 de 1.296 combinações de dados (44,37%) cada;
# o empate, em 146 de 1.296 (11,27%). Vantagem da casa: 1,13% em Player/Banker e 4,48% no empate.
# ===================================================================================
PLAYER, BANKER, EMPATE = "P", "B", "E"
NOMES_LADO = {PLAYER: "PLAYER", BANKER: "BANKER", EMPATE: "EMPATE"}
OPOSTO = {PLAYER: BANKER, BANKER: PLAYER}
PAGA_EMPATE = {2: 88, 12: 88, 3: 25, 11: 25, 4: 10, 10: 10, 5: 6, 9: 6, 6: 4, 7: 4, 8: 4}
DEVOLUCAO_NO_EMPATE = 0.9  # Player/Banker recebem 90% de volta quando dá empate
CHANCE_LADO = 575 / 1296
CHANCE_EMPATE = 146 / 1296
RETORNO_MEDIO_EMPATE = 1238 / 146  # quanto volta, em média, cada R$ 1 num empate que acerta
VANTAGEM_LADO = 1 - (575 * 2 + 146 * DEVOLUCAO_NO_EMPATE) / 1296  # 1,13%
VANTAGEM_EMPATE = 1 - 1238 / 1296                                 # 4,48%
MATEMATICA_BACBO = {
    # acerto mínimo do lado: 2w - 1 + 0,9t = 0  ->  w = (1 - 0,9t) / 2
    "lado": {"chance_teorica": CHANCE_LADO, "acerto_minimo": (1 - DEVOLUCAO_NO_EMPATE * CHANCE_EMPATE) / 2},
    "empate": {"chance_teorica": CHANCE_EMPATE, "acerto_minimo": 1 / RETORNO_MEDIO_EMPATE},
}


@dataclass
class ConfigBacBo:
    valor_por_alvo: float = 10.0
    protecao_empate: bool = True       # cobrir o empate junto com as apostas em Player/Banker?
    valor_protecao_empate: float = 1.0
    banca_inicial: float = 1000.0
    tamanho_historico: int = 30

    def __post_init__(self) -> None:
        if self.valor_por_alvo <= 0 or self.valor_protecao_empate < 0 or self.banca_inicial <= 0:
            raise ValueError("os valores da banca do Bac Bo precisam ser positivos.")


@dataclass(frozen=True)
class RodadaBacBo:
    """Uma rodada: quem ganhou e as somas (quando conhecidas)."""

    resultado: str                 # "P", "B" ou "E"
    soma_player: Optional[int]
    soma_banker: Optional[int]
    horario: datetime

    @classmethod
    def dos_dados(cls, p1: int, p2: int, b1: int, b2: int, horario: Optional[datetime] = None) -> "RodadaBacBo":
        if any(not 1 <= d <= 6 for d in (p1, p2, b1, b2)):
            raise ValueError("dado inválido (tem que ser de 1 a 6)")
        sp, sb = p1 + p2, b1 + b2
        resultado = PLAYER if sp > sb else (BANKER if sb > sp else EMPATE)
        return cls(resultado, sp, sb, horario or datetime.now())

    @classmethod
    def do_resultado(cls, resultado: str, soma: Optional[int] = None,
                     horario: Optional[datetime] = None) -> "RodadaBacBo":
        """Quando só se sabe quem ganhou (modo manual): 'soma' é a soma vencedora, ou a do empate."""
        if resultado not in (PLAYER, BANKER, EMPATE):
            raise ValueError(f"resultado inválido: {resultado!r}")
        if soma is not None and not 2 <= soma <= 12:
            raise ValueError("a soma de dois dados vai de 2 a 12")
        sp = soma if resultado in (PLAYER, EMPATE) else None
        sb = soma if resultado in (BANKER, EMPATE) else None
        return cls(resultado, sp, sb, horario or datetime.now())

    @property
    def soma_vencedora(self) -> Optional[int]:
        return self.soma_banker if self.resultado == BANKER else self.soma_player

    @property
    def paga_empate(self) -> int:
        """Quanto o empate paga nesta rodada. Sem a soma, usa o mínimo (4:1), por segurança."""
        return PAGA_EMPATE.get(self.soma_player, 4) if self.resultado == EMPATE else 0


@dataclass
class PadraoBacBo:
    """Um padrão: olha os resultados (do mais antigo para o mais novo) e devolve o alvo ou None."""

    chave: str
    nome: str
    descricao: str
    detectar: object  # função: List[str] -> Optional[str]

    @property
    def tipo(self) -> str:
        return "empate" if self.chave in ("emp",) or self.chave.endswith(">E") else "lado"


def _sequencia_final(res: List[str]) -> int:
    """Quantos resultados iguais seguidos no fim (o empate quebra a sequência)."""
    if not res or res[-1] == EMPATE:
        return 0
    n = 1
    while n < len(res) and res[-1 - n] == res[-1]:
        n += 1
    return n


def _alternancia_final(res: List[str]) -> int:
    """Tamanho da alternância no fim, ex.: P B P B = 4 (o empate quebra)."""
    if not res or res[-1] == EMPATE:
        return 0
    n = 1
    while n < len(res) and res[-1 - n] != EMPATE and res[-1 - n] != res[-n]:
        n += 1
    return n


def _duplas_2x2(res: List[str]) -> Optional[str]:
    """P P B B (duas duplas): aposta que a próxima dupla começa pelo primeiro lado."""
    if len(res) < 4 or EMPATE in res[-4:]:
        return None
    a, b, c, d = res[-4:]
    if a == b and c == d and a != c and _sequencia_final(res) == 2:
        return a
    return None


# Os padrões prontos. Cada sequência gera uma entrada só (dispara no tamanho exato).
PADROES_BACBO: List[PadraoBacBo] = [
    PadraoBacBo("rep3", "3 iguais → lado oposto", "Três Player (ou Banker) seguidos: aposta no outro lado.",
                lambda r: OPOSTO[r[-1]] if _sequencia_final(r) == 3 else None),
    PadraoBacBo("alt4", "Alternância → continua", "Player, Banker, Player, Banker: aposta que continua alternando.",
                lambda r: OPOSTO[r[-1]] if _alternancia_final(r) == 4 else None),
    PadraoBacBo("rep2", "2 iguais → repete", "Dois iguais seguidos: aposta que repete (segue a tendência).",
                lambda r: r[-1] if _sequencia_final(r) == 2 else None),
    PadraoBacBo("emp", "Empate → empate", "Saiu empate: aposta em empate na rodada seguinte.",
                lambda r: EMPATE if r and r[-1] == EMPATE else None),
    PadraoBacBo("2x2", "Duplas (PPBB) → volta o primeiro", "Duas duplas seguidas: aposta que a próxima começa pelo primeiro lado.",
                _duplas_2x2),
    PadraoBacBo("surf4", "4 iguais → surfa a sequência", "Quatro iguais seguidos: aposta que a sequência continua.",
                lambda r: r[-1] if _sequencia_final(r) == 4 else None),
]


def ler_padroes_personalizados(texto: str) -> Tuple[List[PadraoBacBo], List[str]]:
    """
    Lê padrões escritos por você, um por linha, no formato SEQUÊNCIA -> ALVO
    (P = Player, B = Banker, E = Empate). Exemplos:  PPB -> P   |   BBBB -> P   |   EP -> E
    Um padrão dispara sempre que as últimas rodadas forem exatamente aquela sequência.
    Devolve (padrões válidos, mensagens de erro).
    """
    padroes: List[PadraoBacBo] = []
    erros: List[str] = []
    vistos = set()
    for numero_linha, linha in enumerate(texto.splitlines(), start=1):
        limpa = linha.strip().upper().replace(" ", "")
        if not limpa or limpa.startswith("#"):
            continue
        for separador in ("->", "→", "=>", "=", ">"):
            if separador in limpa:
                sequencia, alvo = limpa.split(separador, 1)
                break
        else:
            erros.append(f"linha {numero_linha}: falta a seta (exemplo: PPB -> P)")
            continue
        if not sequencia or len(sequencia) > 12 or any(c not in "PBE" for c in sequencia) or alvo not in ("P", "B", "E"):
            erros.append(f"linha {numero_linha}: use só P, B e E, com até 12 letras (exemplo: PPB -> P)")
            continue
        chave = f"c:{sequencia}>{alvo}"
        if chave in vistos:
            continue
        vistos.add(chave)
        padroes.append(PadraoBacBo(
            chave, f"{sequencia} → {alvo}",
            f"Sempre que as últimas rodadas forem {sequencia}, aposta em {NOMES_LADO[alvo]}.",
            lambda r, s=list(sequencia), a=alvo: a if r[-len(s):] == s else None))
    return padroes, erros


@dataclass
class SinalBacBo:
    chave: str
    nome: str
    alvo: str            # "P", "B" ou "E"
    rodada_origem: int

    @property
    def tipo(self) -> str:
        return "empate" if self.alvo == EMPATE else "lado"


@dataclass
class ResultadoBacBo:
    sinal: SinalBacBo
    rodada: RodadaBacBo
    status: str          # "GREEN", "EMPATE" ou "LOSS"
    total_apostado: float
    lucro: float


class EstrategiaBacBo:
    """Roda os padrões ativos sobre o histórico e devolve os sinais para a próxima rodada."""

    def __init__(self, padroes: List[PadraoBacBo]) -> None:
        self.padroes = list(padroes)

    def analisar(self, historico: Deque[RodadaBacBo], numero_rodada: int) -> List[SinalBacBo]:
        resultados = [r.resultado for r in historico]
        sinais: List[SinalBacBo] = []
        for padrao in self.padroes:
            try:
                alvo = padrao.detectar(resultados)
            except Exception as erro:  # um padrão com defeito não derruba os outros
                exibir(f"⚠️  Erro no padrão {padrao.nome}: {erro}")
                continue
            if alvo:
                sinais.append(SinalBacBo(padrao.chave, padrao.nome, alvo, numero_rodada))
        return sinais


class BancaBacBo:
    """Liquida cada sinal na rodada seguinte com os pagamentos reais do Bac Bo."""

    def __init__(self, config: ConfigBacBo) -> None:
        self.config = config
        self.saldo = config.banca_inicial
        self.menor_saldo = config.banca_inicial
        self.estatisticas: Dict[str, EstatisticaPadrao] = {}
        self.nomes: Dict[str, str] = {}
        self.tipos: Dict[str, str] = {}
        self.apostado_lado = 0.0
        self.apostado_empate = 0.0

    def liquidar(self, sinal: SinalBacBo, rodada: RodadaBacBo) -> ResultadoBacBo:
        ficha = self.config.valor_por_alvo
        if sinal.alvo == EMPATE:
            apostado, acertou = ficha, rodada.resultado == EMPATE
            self.apostado_empate += ficha
            retorno = ficha * (1 + rodada.paga_empate) if acertou else 0.0
            status = "GREEN" if acertou else "LOSS"
        else:
            protecao = self.config.valor_protecao_empate if self.config.protecao_empate else 0.0
            apostado, acertou = ficha + protecao, rodada.resultado == sinal.alvo
            self.apostado_lado += ficha
            self.apostado_empate += protecao
            if acertou:
                retorno = ficha * 2
            elif rodada.resultado == EMPATE:
                retorno = ficha * DEVOLUCAO_NO_EMPATE + protecao * (1 + rodada.paga_empate)
            else:
                retorno = 0.0
            status = "GREEN" if acertou else ("EMPATE" if rodada.resultado == EMPATE else "LOSS")
        lucro = retorno - apostado

        est = self.estatisticas.setdefault(sinal.chave, EstatisticaPadrao())
        self.nomes[sinal.chave], self.tipos[sinal.chave] = sinal.nome, sinal.tipo
        est.sinais += 1
        est.apostado += apostado
        est.lucro += lucro
        if status == "GREEN":
            est.greens += 1
        elif status == "EMPATE" and lucro > 0:
            est.greens_protecao += 1
        else:
            est.losses += 1
        self.saldo += lucro
        self.menor_saldo = min(self.menor_saldo, self.saldo)
        return ResultadoBacBo(sinal, rodada, status, apostado, lucro)

    def total(self) -> EstatisticaPadrao:
        soma = EstatisticaPadrao()
        for est in self.estatisticas.values():
            for campo in ("sinais", "greens", "greens_protecao", "losses", "apostado", "lucro"):
                setattr(soma, campo, getattr(soma, campo) + getattr(est, campo))
        return soma

    def esperado(self) -> float:
        """Quanto a matemática prevê perder com o que foi apostado (em cada tipo de aposta)."""
        return -(self.apostado_lado * VANTAGEM_LADO + self.apostado_empate * VANTAGEM_EMPATE)


class SimuladorBacBo:
    """Rola quatro dados de verdade (cada face com a mesma chance), como a mesa."""

    def __init__(self, semente: Optional[int] = None) -> None:
        self._rng = random.Random(semente)

    def proxima(self) -> RodadaBacBo:
        return RodadaBacBo.dos_dados(*(self._rng.randint(1, 6) for _ in range(4)))


class MotorBacBo:
    """O mesmo ciclo do motor da roleta: registra, liquida os sinais anteriores, procura novos."""

    LIMITE_FEED = 300
    LIMITE_CURVA = 3000

    def __init__(self, config: ConfigBacBo, padroes: Optional[List[PadraoBacBo]] = None,
                 registrar: bool = True) -> None:
        self.config = config
        self.estrategia = EstrategiaBacBo(padroes if padroes is not None else PADROES_BACBO)
        self.banca = BancaBacBo(config)
        self.historico: Deque[RodadaBacBo] = deque(maxlen=config.tamanho_historico)
        self.pendentes: List[SinalBacBo] = []
        self.total_rodadas = 0
        self.registrar = registrar
        self.resultados: Deque[ResultadoBacBo] = deque(maxlen=self.LIMITE_FEED)
        self.curva: List[Tuple[int, float, float]] = [(0, 0.0, 0.0)]
        self._foto: Optional[tuple] = None

    def processar(self, rodada: RodadaBacBo, permitir_desfazer: bool = False) -> List[ResultadoBacBo]:
        if permitir_desfazer:
            self._foto = (copy.deepcopy(self.banca), self.historico.copy(), list(self.pendentes),
                          self.total_rodadas, list(self.resultados), list(self.curva))
        self.total_rodadas += 1
        self.historico.append(rodada)
        resultados: List[ResultadoBacBo] = []
        for sinal in self.pendentes:
            try:
                resultados.append(self.banca.liquidar(sinal, rodada))
            except Exception as erro:
                exibir(f"⚠️  Erro ao validar {sinal.nome}: {erro}")
        self.pendentes = self.estrategia.analisar(self.historico, self.total_rodadas)
        if self.registrar:
            self.resultados.extend(resultados)
            self.curva.append((self.total_rodadas, self.banca.total().lucro, self.banca.esperado()))
            if len(self.curva) > self.LIMITE_CURVA:
                self.curva = self.curva[:1] + self.curva[1:-1:2] + self.curva[-1:]
        return resultados

    def desfazer(self) -> bool:
        if self._foto is None:
            return False
        banca, historico, pendentes, total, resultados, curva = self._foto
        self.banca, self.historico, self.pendentes, self.total_rodadas = banca, historico, pendentes, total
        self.resultados = deque(resultados, maxlen=self.LIMITE_FEED)
        self.curva = curva
        self._foto = None
        return True


def executar_backtest_bacbo(rodadas: int, semente: Optional[int], config: Optional[ConfigBacBo] = None,
                            padroes: Optional[List[PadraoBacBo]] = None, ao_progredir=None) -> MotorBacBo:
    """Backtest do Bac Bo com dados simulados (mesma semente = mesmas rodadas)."""
    simulador = SimuladorBacBo(semente)
    motor = MotorBacBo(config or ConfigBacBo(), padroes, registrar=False)
    passo = max(1, rodadas // 100)
    curva = [(0, 0.0, 0.0)]
    for n in range(1, rodadas + 1):
        motor.processar(simulador.proxima())
        if n % passo == 0 or n == rodadas:
            curva.append((n, motor.banca.total().lucro, motor.banca.esperado()))
            if ao_progredir is not None:
                ao_progredir(n / rodadas)
    motor.curva = curva
    return motor


def rodar_bacbo_terminal(args: argparse.Namespace) -> None:
    """No terminal, o Bac Bo tem o backtest (os outros modos ficam no painel visual)."""
    if args.backtest is None:
        exibir("No terminal, o Bac Bo tem só o backtest:  python robo_roleta.py --jogo bacbo --backtest 1000000")
        exibir("Para os modos manual e simulador, use o painel visual (opção 6 do menu).")
        return
    if args.backtest <= 0:
        exibir("⛔ Configuração inválida: --backtest precisa de um número positivo de rodadas.")
        sys.exit(1)
    inicio = time.time()
    exibir(f"🧪 BACKTEST BAC BO: simulando {formatar_inteiro(args.backtest)} rodadas...")
    motor = executar_backtest_bacbo(args.backtest, args.semente)
    total, banca = motor.banca.total(), motor.banca
    exibir("=" * 72)
    exibir("🏁 RELATÓRIO FINAL — BAC BO")
    exibir("=" * 72)
    exibir(f"Rodadas analisadas      : {formatar_inteiro(args.backtest)}")
    exibir(f"Tempo de execução       : {time.time() - inicio:.1f} s")
    exibir(f"Sinais disparados       : {formatar_inteiro(total.sinais)}  (✅ {formatar_inteiro(total.greens)}"
           f" | salvos no empate {formatar_inteiro(total.greens_protecao)} | ❌ {formatar_inteiro(total.losses)})")
    exibir(f"Banca inicial → final   : {formatar_reais(banca.config.banca_inicial)} → {formatar_reais(banca.saldo)}")
    exibir(f"Total apostado          : {formatar_reais(total.apostado)}")
    exibir(f"Resultado real          : {formatar_reais(total.lucro, com_sinal=True)}")
    exibir(f"Esperado pela matemática: {formatar_reais(banca.esperado(), com_sinal=True)}"
           f"  (1,13% em Player/Banker e 4,48% no empate)")
    exibir("-" * 72)
    for padrao in PADROES_BACBO:
        est = banca.estatisticas.get(padrao.chave, EstatisticaPadrao())
        mat = MATEMATICA_BACBO[padrao.tipo]
        exibir(f"   {padrao.nome:<34} | {formatar_inteiro(est.sinais):>7} sinais | acerto {formatar_pct(est.taxa_acerto):>6}"
               f" | teórico {formatar_pct(mat['chance_teorica']):>6} | mínimo {formatar_pct(mat['acerto_minimo']):>6}"
               f" | {formatar_reais(est.lucro, com_sinal=True)}")
    exibir("=" * 72)


# ===================================================================================
# 12) BAC BO NO PAINEL VISUAL
# -----------------------------------------------------------------------------------
# Mesmo painel e mesmos modos da roleta. Escolha o jogo no topo da barra lateral.
# A sessão da roleta e a do Bac Bo ficam guardadas separadas: trocar de jogo não apaga nada.
# ===================================================================================
JOGO_ROLETA, JOGO_BACBO = "Roleta", "Bac Bo"
TAMANHO_GATILHO_BACBO = {"rep3": 3, "alt4": 4, "rep2": 2, "emp": 1, "2x2": 4, "surf4": 4}
SEM_SOMA = "Não sei"


def _tamanho_gatilho(chave: str) -> int:
    """Quantas rodadas formam o gatilho (para mostrar a sequência que disparou)."""
    if chave.startswith("c:"):
        return len(chave[2:].split(">")[0])
    return TAMANHO_GATILHO_BACBO.get(chave, 3)


# -----------------------------------------------------------------------------------
# Leitura automática da mesa de Bac Bo
# -----------------------------------------------------------------------------------
# Na mesa da Evolution, o quadro de baixo à esquerda (o "bead road") tem uma bolinha por
# rodada, preenchido de cima para baixo e da esquerda para a direita. Cada bolinha é um SVG:
#     <g data-type="roadItemColor" fill="#2F63DF"> ... </g>  <text>P</text>
# A cor diz quem ganhou (azul = Player, vermelho = Banker, dourado/verde = Empate) e o texto
# mostra a letra (P, B, T) ou, se você clicar no quadro, a soma dos dados.
# O script acha as bolinhas, junta as do mesmo quadro e põe em ordem pela POSIÇÃO na tela
# (coluna por coluna, de cima para baixo). Assim ele não depende de como a Evolution
# organiza o código por dentro, só do data-type, que é um nome legível e estável.
JS_LER_BACBO = r"""
() => {
    const SELETOR = '[data-type="roadItemColor"]';
    const visivel = el => el.getClientRects().length > 0;
    const raizes = [document];
    for (let i = 0; i < raizes.length; i++) {
        for (const el of raizes[i].querySelectorAll('*')) {
            if (el.shadowRoot) raizes.push(el.shadowRoot);
        }
    }
    let total = 0, visiveis = 0;
    const blocos = new Set();
    for (const raiz of raizes) {
        for (const el of raiz.querySelectorAll(SELETOR)) {
            total++;
            if (!visivel(el)) continue;
            visiveis++;
            // sobe até o menor bloco com 7+ bolinhas (uma coluna sozinha tem no máximo 6)
            let bloco = el.parentElement;
            while (bloco && bloco.querySelectorAll(SELETOR).length < 7) bloco = bloco.parentElement;
            if (bloco) blocos.add(bloco);
        }
    }
    const finais = [...blocos].filter(b => ![...blocos].some(o => o !== b && b.contains(o)));
    const grupos = finais.map(bloco => {
        const lista = [];
        for (const el of bloco.querySelectorAll(SELETOR)) {
            if (!visivel(el)) continue;
            // o texto da bolinha: sobe enquanto o pedaço ainda for só desta bolinha
            let caixa = el.parentElement, texto = null;
            while (caixa && caixa !== bloco && caixa.querySelectorAll(SELETOR).length === 1) {
                texto = caixa.querySelector('text');
                if (texto) break;
                caixa = caixa.parentElement;
            }
            const r = el.getBoundingClientRect();
            const pintado = el.querySelector('[fill]');
            lista.push({x: r.left + r.width / 2, y: r.top + r.height / 2, w: r.width || 1,
                        t: texto ? texto.textContent.trim() : '',
                        f: el.getAttribute('fill') || (pintado ? pintado.getAttribute('fill') : '') || '',
                        s: el.getAttribute('stroke') || ''});
        }
        // ordem do quadro: coluna por coluna (esquerda -> direita), de cima para baixo
        lista.sort((a, b) => a.x - b.x);
        const colunas = [];
        for (const it of lista) {
            const ultima = colunas[colunas.length - 1];
            if (ultima && Math.abs(it.x - ultima.x) < Math.max(2, it.w * 0.45)) ultima.itens.push(it);
            else colunas.push({x: it.x, itens: [it]});
        }
        const itens = [];
        for (const col of colunas) {
            col.itens.sort((a, b) => a.y - b.y);
            for (const it of col.itens) itens.push([it.t, it.f, it.s]);
        }
        const nomeClasse = typeof bloco.className === 'string' ? bloco.className
                         : (bloco.className && bloco.className.baseVal) || '';
        return {chave: bloco.tagName + '|' + (bloco.getAttribute('data-type') || bloco.getAttribute('data-role') || '')
                       + '|' + nomeClasse, itens: itens};
    });
    return {total: total, visiveis: visiveis, grupos: grupos};
}
"""

LETRAS_BACBO = {"P": PLAYER, "J": PLAYER, "B": BANKER, "T": EMPATE, "E": EMPATE}


def _ler_cor(cor: str) -> Optional[Tuple[int, int, int]]:
    """'#2F63DF', '#26d' ou 'rgb(47, 99, 223)' -> (47, 99, 223)."""
    cor = (cor or "").strip().lower()
    try:
        if cor.startswith("#"):
            hexa = cor[1:]
            if len(hexa) in (3, 4):
                hexa = "".join(c * 2 for c in hexa[:3])
            return int(hexa[0:2], 16), int(hexa[2:4], 16), int(hexa[4:6], 16)
        if cor.startswith("rgb"):
            partes = cor[cor.index("(") + 1:cor.index(")")].replace("/", ",").split(",")
            return tuple(int(float(p)) for p in partes[:3])  # type: ignore[return-value]
    except (ValueError, IndexError):
        return None
    return None


def _lado_pela_cor(cor: str) -> Optional[str]:
    """Azul = Player, vermelho = Banker, dourado/amarelo/verde = Empate."""
    rgb = _ler_cor(cor)
    if rgb is None:
        return None
    r, g, b = rgb
    if r > b + 50 and g > b + 30 and g >= 0.55 * r:
        return EMPATE   # dourado / amarelo
    if g > r + 30 and g > b + 30:
        return EMPATE   # verde
    if b > r + 30 and b >= g:
        return PLAYER
    if r > g + 50 and r > b + 30:
        return BANKER
    return None


def _soma_valida(soma) -> Optional[int]:
    try:
        soma = int(soma)
    except (TypeError, ValueError):
        return None
    return soma if 2 <= soma <= 12 else None


def _item_bacbo(texto: str, preenchimento: str, contorno: str) -> Optional[Tuple[str, Optional[int]]]:
    """Uma bolinha do quadro -> (resultado, soma). None se não der para saber quem ganhou."""
    texto = (texto or "").strip().upper()
    soma = _soma_valida(texto) if texto.isdigit() else None
    lado = LETRAS_BACBO.get(texto)
    if lado is None:
        cor = preenchimento if preenchimento and preenchimento.lower() not in ("none", "transparent") else contorno
        lado = _lado_pela_cor(cor)
    return (lado, soma) if lado else None


class ColetorNavegadorBacBo(ColetorNavegador):
    """
    Lê a mesa de Bac Bo pelo mesmo Chrome do robô (mesma conexão, perfil, modo escondido etc.).
    A faixa é o quadro de bolinhas da mesa, sempre do mais antigo para o mais novo.
    """

    NOME_MESA = "mesa de Bac Bo"
    MINIMO_QUADRO = 7      # bolinhas mínimas para um quadro contar
    EMENDA_MINIMA = 8      # rodadas em comum para confirmar onde duas leituras se emendam

    def _ler_grupos(self, so_do_host: Optional[str] = None,
                    diagnostico: Optional[List[str]] = None) -> List[Tuple[str, str, list]]:
        desconectado = self._navegador is not None and not self._navegador.is_connected()
        paginas = [] if desconectado else self._contexto.pages
        if not paginas:
            exibir("\n🌐 O navegador foi fechado.")
            raise PedidoEncerrar()
        grupos: List[Tuple[str, str, list]] = []
        vistos = set()
        for n_aba, pagina in enumerate(paginas, start=1):
            for frame in pagina.frames:
                host = urlparse(frame.url).netloc
                if so_do_host is not None and host != so_do_host:
                    continue
                try:
                    leitura = frame.evaluate(JS_LER_BACBO)
                except self._ErroPlaywright as erro:
                    if diagnostico is not None and host:
                        diagnostico.append(f"aba {n_aba} | {host}: não consegui ler "
                                           f"({str(erro).splitlines()[0][:70]})")
                    continue
                if diagnostico is not None and (leitura["total"] or not diagnostico):
                    tamanhos = [len(g["itens"]) for g in leitura["grupos"]]
                    diagnostico.append(f"aba {n_aba} | {host or '(vazio)'}: {leitura['total']} bolinhas "
                                       f"no código, {leitura['visiveis']} visíveis, quadros {tamanhos}")
                for grupo in leitura["grupos"]:
                    brutos = grupo["itens"]
                    itens = [_item_bacbo(*b) for b in brutos]
                    com_texto = sum(1 for b in brutos if b[0])
                    # O quadro certo tem letra ou soma em todas as bolinhas e todas com cor conhecida
                    # (os outros quadros da mesa usam bolinhas vazadas, sem texto).
                    if len(itens) < self.MINIMO_QUADRO or None in itens or com_texto < 0.8 * len(itens):
                        continue
                    if (host, grupo["chave"]) in vistos:
                        continue
                    vistos.add((host, grupo["chave"]))
                    grupos.append((host, grupo["chave"], [list(i) for i in itens]))
        return grupos

    @staticmethod
    def visao_candidata(itens: list) -> list:
        return list(reversed(itens[-20:]))  # as 20 últimas, a mais recente primeiro

    def confirmar_faixa(self, host: str, chave: str, itens: list, invertida: bool = False) -> list:
        self._host, self._chave, self._invertida, self._ultima = host, chave, False, list(itens)
        self._pendente = None
        self._fila.clear()
        return list(itens)  # já vem do mais antigo para o mais novo

    @staticmethod
    def evento_novo(item) -> dict:
        return {"tipo": "rodada", "r": item[0], "soma": item[1]}

    @classmethod
    def calcular_novos_bacbo(cls, anterior: List[str], atual: List[str]) -> Optional[int]:
        """
        Quantas rodadas novas entraram no fim do quadro (as listas vão do mais antigo ao mais novo).
        Quando o quadro enche, a coluna mais antiga sai pela esquerda; por isso procura o menor
        'k' (rodadas que saíram pelo começo) em que o resto da leitura anterior abre a atual:
            anterior P B B P E P  e  atual P B B P E P B        ->  1
            anterior P B B P E P  e  atual B P E P B (saiu 2)   ->  1
        Devolve None se não achar a emenda (quadro reiniciou ou leitura muito atrasada).
        """
        if atual == anterior:
            return 0
        for k in range(len(anterior)):
            sobra = anterior[k:]
            if len(sobra) < cls.EMENDA_MINIMA:
                break
            if atual[:len(sobra)] == sobra:
                return len(atual) - len(sobra)
        return None

    def _verificar_novos(self) -> None:
        atual = self._ler_faixa_escolhida()
        if atual is None:
            self._tratar_faixa_sumida()
            return
        if self._avisou_sumico:
            exibir("✅ Quadro de resultados encontrado de novo.")
        self._sumiu_desde, self._avisou_sumico = None, False
        if atual == self._ultima:
            self._pendente = None
            return
        if atual != self._pendente:  # só aceita a mudança depois de duas leituras iguais
            self._pendente = atual
            return
        self._pendente = None
        novos = self.calcular_novos_bacbo([i[0] for i in self._ultima], [i[0] for i in atual])
        if novos is None:
            exibir("⚠️  Perdi a sequência do quadro (a mesa recarregou ou o quadro reiniciou). "
                   "Vou considerar só a última rodada.")
            novos = 1 if atual else 0
        self._ultima = atual
        if novos:
            self._fila.extend(atual[-novos:])


def _novos_depois_de(anterior: List[str], atual: List[str]) -> Optional[int]:
    """
    Painel: a faixa foi confirmada de novo no meio da sessão. Acha onde as últimas rodadas
    que o painel já tinha aparecem no quadro e devolve a posição a partir da qual são novas.
    """
    m = len(anterior)
    if m < ColetorNavegadorBacBo.EMENDA_MINIMA:
        return None
    for fim in range(len(atual), m - 1, -1):  # a ocorrência mais recente vale
        if atual[fim - m:fim] == anterior:
            return fim
    return None


class SessaoBacBo:
    """Estado do Bac Bo no painel: sessão manual/simulador, padrões ligados e o último backtest."""

    def __init__(self, no_meu_pc: bool = False) -> None:
        self.trava = threading.RLock()
        self.no_meu_pc = no_meu_pc
        salvo = ler_config_painel() if no_meu_pc else dict(CONFIG_PAINEL_PADRAO)
        desligados = salvo.get("bacbo_padroes_desligados") or []
        self.desligados: List[str] = [c for c in desligados if isinstance(c, str)]
        self.extras_txt: str = str(salvo.get("bacbo_padroes_extras") or "")
        self.erros_padroes: List[str] = []
        self.padroes: List[PadraoBacBo] = self._montar_padroes()
        self.config = ConfigBacBo()
        self.motor = MotorBacBo(self.config, self.padroes)
        self.sim = {"rodando": False, "dados": None, "rng": None, "proximo": 0.0, "rapido": False}
        self.backtest: Optional[dict] = None
        self.leitor: Optional[LeitorProcesso] = None

    # --- leitura automática (mesmos nomes da SessaoWeb, para reaproveitar os controles) ---
    def iniciar_leitor(self, url: Optional[str], escondido: bool = False, auto_confirmar: bool = False) -> None:
        with self.trava:
            self.parar_leitor()
            self.leitor = LeitorProcesso(url or None, escondido=escondido, auto_confirmar=auto_confirmar, jogo="bacbo")

    def parar_leitor(self) -> None:
        with self.trava:
            if self.leitor is not None:
                self.leitor.parar()
                self.leitor = None

    def leitor_ativo(self) -> bool:
        return self.leitor is not None and self.leitor.ativo()

    # --- padrões -------------------------------------------------------------------
    def _montar_padroes(self) -> List[PadraoBacBo]:
        extras, self.erros_padroes = ler_padroes_personalizados(self.extras_txt)
        return [p for p in PADROES_BACBO if p.chave not in self.desligados] + extras

    def atualizar_padroes(self, desligados: List[str], extras_txt: str) -> None:
        with self.trava:
            if desligados == self.desligados and extras_txt == self.extras_txt:
                return
            self.desligados, self.extras_txt = list(desligados), extras_txt
            self.padroes = self._montar_padroes()
            # Vale na hora: o alerta da tela passa a mostrar só o que os padrões novos enxergam
            self.motor.estrategia.padroes = list(self.padroes)
            self.motor.pendentes = self.motor.estrategia.analisar(self.motor.historico, self.motor.total_rodadas)
            if self.no_meu_pc:
                salvar_config_painel({"bacbo_padroes_desligados": self.desligados,
                                      "bacbo_padroes_extras": self.extras_txt})

    def padroes_sao_os_prontos(self) -> bool:
        return [p.chave for p in self.padroes] == [p.chave for p in PADROES_BACBO]

    # --- sessão --------------------------------------------------------------------
    def nova_sessao(self, config: ConfigBacBo) -> None:
        with self.trava:
            self.config = config
            self.motor = MotorBacBo(config, self.padroes)

    def iniciar_sim(self, rapido: bool, semente: Optional[int]) -> None:
        with self.trava:
            self.sim.update(rodando=True, dados=SimuladorBacBo(semente), rapido=rapido,
                            rng=random.Random(None if semente is None else semente + 1))
            self.sim["proximo"] = time.time() + self._intervalo_sim()

    def _intervalo_sim(self) -> float:
        return 1.0 if self.sim["rapido"] else self.sim["rng"].uniform(15.0, 20.0)

    def tick(self) -> None:
        with self.trava:
            if self.leitor is not None:
                historico = self.leitor.pegar_historico()
                if historico:
                    rodadas = [RodadaBacBo.do_resultado(r, _soma_valida(soma)) for r, soma in historico]
                    if self.motor.total_rodadas == 0 and not self.motor.historico:
                        _carregar_historico_bacbo(self.motor, rodadas[-self.config.tamanho_historico:])
                    else:
                        # Faixa confirmada de novo no meio da sessão: processa só o que saiu nesse intervalo
                        inicio = _novos_depois_de([r.resultado for r in self.motor.historico],
                                                  [r.resultado for r in rodadas])
                        for rodada in rodadas[inicio:] if inicio is not None else []:
                            self.motor.processar(rodada)
                for resultado, soma in self.leitor.pegar_numeros():
                    if resultado in (PLAYER, BANKER, EMPATE):
                        self.motor.processar(RodadaBacBo.do_resultado(resultado, _soma_valida(soma)))
            if self.sim["rodando"]:
                agora, feitos = time.time(), 0
                while agora >= self.sim["proximo"] and feitos < 30:
                    self.motor.processar(self.sim["dados"].proxima())
                    self.sim["proximo"] += self._intervalo_sim()
                    feitos += 1


def obter_bacbo(sessao: SessaoWeb, no_meu_pc: bool) -> SessaoBacBo:
    """A sessão do Bac Bo mora dentro da sessão do painel (criada na primeira vez)."""
    if getattr(sessao, "bacbo", None) is None:
        sessao.bacbo = SessaoBacBo(no_meu_pc)
    return sessao.bacbo


def _carregar_historico_bacbo(motor: MotorBacBo, rodadas: List[RodadaBacBo]) -> None:
    """Resultados que a mesa já mostrava (do mais antigo para o mais novo), sem apostar."""
    for rodada in rodadas:
        motor.historico.append(rodada)
    motor.pendentes = motor.estrategia.analisar(motor.historico, motor.total_rodadas)


class HtmlBacBo:
    """Pedaços visuais do Bac Bo (usam o mesmo CSS do painel da roleta)."""

    COR = {PLAYER: Html.CORES["player"], BANKER: Html.CORES["red"], EMPATE: Html.CORES["gold"]}
    CLASSE = {PLAYER: "p", BANKER: "b", EMPATE: "e"}
    PREVISTO = "Previsto pela matemática (1,13% em Player/Banker e 4,48% no empate)"

    @classmethod
    def chip(cls, rodada: RodadaBacBo, extra: str = "") -> str:
        letra, soma = rodada.resultado, rodada.soma_vencedora
        if rodada.soma_player is not None and rodada.soma_banker is not None and letra != EMPATE:
            titulo = f"{NOMES_LADO[letra]} · Player {rodada.soma_player} x {rodada.soma_banker} Banker"
        else:
            titulo = NOMES_LADO[letra] + (f" · soma {soma}" if soma else "")
        sub = f"<small>{soma}</small>" if soma else ""
        return f'<span class="bb-chip {cls.CLASSE[letra]} {extra}" title="{titulo}">{letra}{sub}</span>'

    @classmethod
    def faixa(cls, historico: Deque[RodadaBacBo]) -> str:
        rodadas = list(historico)[::-1]  # mais recente primeiro
        if not rodadas:
            return ('<div class="rr-bloco"><div class="rr-h">Últimas rodadas</div>'
                    '<span class="rr-nota">Nenhuma rodada ainda. Os resultados aparecem aqui assim que saírem.</span></div>')
        conta = {lado: sum(1 for r in rodadas if r.resultado == lado) for lado in (PLAYER, BANKER, EMPATE)}
        chips = "".join(cls.chip(r, "nova" if i == 0 else "") for i, r in enumerate(rodadas))
        return (f'<div class="rr-bloco"><div class="rr-h">Últimas rodadas<small>mais recente à esquerda · '
                f'P {conta[PLAYER]} · B {conta[BANKER]} · E {conta[EMPATE]}</small></div>'
                f'<div class="rr-pedras">{chips}</div></div>')

    @staticmethod
    def cartoes(motor: MotorBacBo) -> str:
        banca, total = motor.banca, motor.banca.total()
        variacao = banca.saldo - motor.config.banca_inicial
        if total.sinais:
            teorico = sum(est.sinais * MATEMATICA_BACBO[banca.tipos[ch]]["chance_teorica"]
                          for ch, est in banca.estatisticas.items()) / total.sinais
            acerto_txt, acerto_det = formatar_pct(total.taxa_acerto), f"chance real dos alvos: {formatar_pct(teorico)}"
        else:
            acerto_txt, acerto_det = "—", "aparece depois do primeiro sinal"
        esperado = banca.esperado()
        return '<div class="rr-cartoes">' + "".join([
            Html.cartao("Banca fictícia", formatar_reais(banca.saldo),
                        f'<span class="{"rr-pos" if variacao >= 0 else "rr-neg"}">{formatar_reais(variacao, com_sinal=True)}</span>'
                        f" desde o início"),
            Html.cartao("Acerto geral", acerto_txt, acerto_det),
            Html.cartao("Sinais conferidos", formatar_inteiro(total.sinais),
                        f'<span class="rr-pos">{total.greens} GREEN</span> · <span class="rr-neg">{total.losses} LOSS</span>'
                        f" · {total.greens_protecao} salvos no empate"),
            Html.cartao("Resultado vs. esperado", formatar_reais(total.lucro, com_sinal=True),
                        f"a matemática previa {formatar_reais(esperado, com_sinal=True)}",
                        "rr-pos" if total.lucro > 0 else ("rr-neg" if total.lucro < 0 else "")),
        ]) + "</div>"

    @classmethod
    def alerta(cls, sinal: SinalBacBo, motor: MotorBacBo) -> str:
        cfg = motor.config
        gatilho = "".join(cls.chip(r, "pq") for r in list(motor.historico)[-_tamanho_gatilho(sinal.chave):])
        alvo = (f'<span class="rr-alvo"><span class="sw" style="background:{cls.COR[sinal.alvo]}"></span>'
                f'{NOMES_LADO[sinal.alvo]}</span>')
        if sinal.alvo == EMPATE:
            valor = (f'<div class="rr-valor">{formatar_reais(cfg.valor_por_alvo)}'
                     f'<small>no empate · paga de 4:1 a 88:1, conforme a soma dos dados</small></div>')
            protecao = '<div class="rr-valor" style="font-size:1rem">Não se aplica</div>'
        else:
            com_protecao = cfg.protecao_empate and cfg.valor_protecao_empate > 0
            total = cfg.valor_por_alvo + (cfg.valor_protecao_empate if com_protecao else 0.0)
            valor = (f'<div class="rr-valor">{formatar_reais(cfg.valor_por_alvo)}'
                     f'<small>no {NOMES_LADO[sinal.alvo]} · {formatar_reais(total)} no total</small></div>')
            if com_protecao:
                protecao = (f'<div class="rr-valor" style="display:flex;align-items:center;gap:10px">'
                            f'{cls.chip(RodadaBacBo.do_resultado(EMPATE), "pq")}{formatar_reais(cfg.valor_protecao_empate)}'
                            f'<small style="display:inline">no empate</small></div>')
            else:
                protecao = ('<div class="rr-valor" style="font-size:1rem">Sem proteção'
                            '<small>no empate volta 90% da entrada</small></div>')
        return (f'<div class="rr-alerta"><div class="tag">Gatilho ativado</div>'
                f'<div class="pad">{html.escape(sinal.nome)}</div><div class="grade">'
                f'<div><div class="lbl">Alvo da entrada</div><div class="rr-alvos">{alvo}</div>'
                f'<div class="lbl" style="margin-top:14px">Sequência que disparou</div><div class="rr-pedras">{gatilho}</div></div>'
                f'<div><div class="lbl">Valor sugerido</div>{valor}</div>'
                f'<div><div class="lbl">Proteção</div>{protecao}</div>'
                f'</div><div class="rr-validade">Vale só para a próxima rodada. O painel confere sozinho e lança na banca fictícia.</div></div>')

    @classmethod
    def alertas(cls, motor: MotorBacBo) -> str:
        lados = {s.alvo for s in motor.pendentes}
        aviso = ('<div class="rr-aviso">Sinais opostos nesta rodada (Player e Banker): '
                 'entrando nos dois, um anula o outro.</div>') if {PLAYER, BANKER} <= lados else ""
        return "".join(cls.alerta(s, motor) for s in motor.pendentes) + aviso

    @classmethod
    def sem_alerta(cls, motor: MotorBacBo, padroes: List[PadraoBacBo]) -> str:
        ultimo = cls.chip(motor.historico[-1], "pq") if motor.historico else ""
        if padroes:
            texto = f"{len(padroes)} padrões ligados · o alerta aparece aqui assim que uma sequência se formar"
        else:
            texto = "Nenhum padrão ligado: escolha os padrões em “Padrões do Bac Bo”, na barra lateral"
        return f'<div class="rr-calmo">{ultimo}<div><b>Nenhum gatilho ativo</b><br><span>{texto}</span></div></div>'

    @staticmethod
    def feed(motor: MotorBacBo, limite: int = 10) -> str:
        itens = list(motor.resultados)[-limite:][::-1]
        if not itens:
            return ('<div class="rr-bloco"><div class="rr-h">Últimas entradas</div>'
                    '<span class="rr-nota">Os sinais conferidos aparecem aqui.</span></div>')
        linhas = []
        for r in itens:
            classe = {"GREEN": "g", "LOSS": "l", "EMPATE": "z"}[r.status]
            soma = r.rodada.soma_vencedora
            saiu = NOMES_LADO[r.rodada.resultado] + (f" {soma}" if soma else "")
            linhas.append(f'<div class="rr-item"><span class="rr-badge {classe}">{r.status}</span>'
                          f'<span class="t">{html.escape(r.sinal.nome)} · alvo {NOMES_LADO[r.sinal.alvo]} · saiu {saiu}</span>'
                          f'<span class="x {"rr-pos" if r.lucro > 0 else "rr-neg"}">{formatar_reais(r.lucro, com_sinal=True)}</span></div>')
        return f'<div class="rr-bloco"><div class="rr-h">Últimas entradas</div><div class="rr-feed">{"".join(linhas)}</div></div>'

    @staticmethod
    def tabela(banca: BancaBacBo, padroes: List[PadraoBacBo], titulo: str = "Desempenho por padrão") -> str:
        ligados = {p.chave: p for p in padroes}
        ordem = list(ligados) + [ch for ch in banca.estatisticas if ch not in ligados]
        if not ordem:
            return (f'<div class="rr-bloco"><div class="rr-h">{titulo}</div>'
                    '<span class="rr-nota">Nenhum padrão ligado.</span></div>')
        linhas = []
        for ch in ordem:
            est = banca.estatisticas.get(ch, EstatisticaPadrao())
            padrao = ligados.get(ch)
            nome = padrao.nome if padrao else banca.nomes.get(ch, ch) + " (desligado)"
            mat = MATEMATICA_BACBO[padrao.tipo if padrao else banca.tipos.get(ch, "lado")]
            acerto = formatar_pct(est.taxa_acerto) if est.sinais else "—"
            linhas.append(f"<tr><td>{html.escape(nome)}</td><td>{formatar_inteiro(est.sinais)}</td><td>{acerto}</td>"
                          f"<td>{formatar_pct(mat['chance_teorica'])}</td><td>{formatar_pct(mat['acerto_minimo'])}</td>"
                          f'<td class="{"rr-pos" if est.lucro > 0 else ("rr-neg" if est.lucro < 0 else "")}">'
                          f"{formatar_reais(est.lucro, com_sinal=True)}</td></tr>")
        return (f'<div class="rr-bloco"><div class="rr-h">{titulo}</div><table class="rr-tabela"><thead><tr><th>Padrão</th><th>Sinais</th>'
                f"<th>Acerto</th><th>Chance real</th><th>Para empatar</th><th>Resultado</th></tr></thead>"
                f'<tbody>{"".join(linhas)}</tbody></table>'
                f'<div class="rr-nota">Acerto é quantas vezes o alvo saiu. Em Player ou Banker, o empate dos dados não conta como acerto '
                f'(volta 90% da entrada). Para empatar considera só a aposta principal, sem a proteção. '
                f"Com poucos sinais o acerto oscila muito; com muitos, ele encosta na chance real.</div></div>")


def _ajustes_bacbo(st, bacbo: SessaoBacBo) -> Tuple[dict, ConfigBacBo, bool]:
    """Ajustes da banca fictícia do Bac Bo (na barra lateral)."""
    with st.expander("Ajustes da banca fictícia"):
        valor = st.number_input("Valor por entrada (R$)", min_value=1.0, max_value=100000.0, value=10.0, step=1.0, key="bb_valor")
        cobrir = st.checkbox("Cobrir o empate", value=True, key="bb_emp_on")
        valor_emp = st.number_input("Valor no empate (R$)", min_value=0.0, max_value=100000.0, value=1.0, step=0.5, key="bb_emp_valor")
        banca_ini = st.number_input("Banca inicial (R$)", min_value=1.0, max_value=10_000_000.0, value=1000.0, step=100.0, key="bb_banca")
        st.caption("A proteção acompanha as entradas em Player ou Banker. Os valores padrão são os do teste de aceitação.")
    ajustes = dict(valor_por_alvo=float(valor), protecao_empate=bool(cobrir),
                   valor_protecao_empate=float(valor_emp), banca_inicial=float(banca_ini))
    try:
        config = ConfigBacBo(**ajustes)
    except ValueError as erro:
        st.error(f"Ajuste inválido: {erro}")
        config = ConfigBacBo()
    mudou = any(getattr(bacbo.config, k) != v for k, v in ajustes.items())
    return ajustes, config, mudou


def _padroes_bacbo(st, bacbo: SessaoBacBo) -> None:
    """Liga/desliga os padrões prontos e recebe os seus (um por linha, tipo PPB -> P)."""
    nomes = {p.chave: p.nome for p in PADROES_BACBO}
    # O valor inicial vem do que ficou guardado (no PC, do arquivo de configuração)
    if "bb_pad_sel" not in st.session_state:
        st.session_state["bb_pad_sel"] = [nomes[ch] for ch in nomes if ch not in bacbo.desligados]
    if "bb_pad_extra" not in st.session_state:
        st.session_state["bb_pad_extra"] = bacbo.extras_txt
    with st.expander("Padrões do Bac Bo"):
        escolhidos = st.multiselect("Padrões prontos ligados", list(nomes.values()), key="bb_pad_sel")
        texto = st.text_area("Seus padrões (um por linha)", key="bb_pad_extra", height=120,
                             placeholder="PPB -> P\nBBBB -> P\nEP -> E")
        bacbo.atualizar_padroes([ch for ch, nome in nomes.items() if nome not in escolhidos], texto or "")
        for erro in bacbo.erros_padroes:
            st.error(erro)
        st.caption("P = Player, B = Banker, E = Empate. O padrão dispara quando as últimas rodadas forem "
                   "exatamente a sequência da esquerda, e a entrada é na letra da direita. "
                   f"Ligados agora: {len(bacbo.padroes)}.")


def _cabecalho_bacbo(st, bacbo: SessaoBacBo, modo: str, tem_playwright: bool = True) -> None:
    if modo == MODO_AUTO and not tem_playwright:
        status = ("Só no computador", "alerta")
    elif modo == MODO_AUTO:
        fase = bacbo.leitor.fase if bacbo.leitor else None
        status = {"iniciando": ("Conectando ao Chrome", "alerta"), "conectando": ("Conectando ao Chrome", "alerta"),
                  "procurando": ("Procurando o quadro", "alerta"), "lendo": ("Lendo a mesa ao vivo", "on"),
                  "erro": ("Erro na leitura", ""), "fim": ("Leitura encerrada", "")}.get(fase, ("Parado", ""))
    elif modo == MODO_SIM:
        status = ("Simulando", "on") if bacbo.sim["rodando"] else ("Pausado", "")
    elif modo == MODO_MANUAL:
        status = ("Aguardando a próxima rodada", "on")
    else:
        status = ("Backtest", "")
    st.markdown(f'<div class="rr-topo"><div><div class="rr-sub">Bac Bo · {html.escape(modo)}</div>'
                f'<div class="rr-titulo" role="heading" aria-level="1">Painel de sinais</div></div>'
                f'<span class="rr-status {status[1]}"><i></i>{status[0]}</span></div>', unsafe_allow_html=True)


def app_bacbo(st, bacbo: SessaoBacBo, modo: str, no_meu_pc: bool, config_tela: ConfigBacBo) -> None:
    """A tela do Bac Bo, chamada pelo app_web quando o jogo escolhido é o Bac Bo."""
    if modo == MODO_BACKTEST:
        _cabecalho_bacbo(st, bacbo, modo)
        demonstracao = None
        if not no_meu_pc:
            @st.cache_resource(show_spinner="Rodando o backtest de 1.000.000 de rodadas de Bac Bo (só na primeira visita)...")
            def backtest_demonstracao_bacbo() -> dict:
                inicio = time.time()
                motor = executar_backtest_bacbo(1_000_000, 42)
                return {"rodadas": 1_000_000, "semente": 42, "motor": motor, "padroes": list(PADROES_BACBO),
                        "segundos": time.time() - inicio, "padrao": True, "demonstracao": True}
            demonstracao = backtest_demonstracao_bacbo
        _tela_backtest_bacbo(st, bacbo, config_tela, demonstracao)
        return

    tem_playwright = importlib.util.find_spec("playwright") is not None
    if modo == MODO_MANUAL:
        _cabecalho_bacbo(st, bacbo, modo)
        _tela_manual_bacbo(st, bacbo)

    ao_vivo = bacbo.leitor_ativo() or bacbo.sim["rodando"]

    def painel_bacbo() -> None:
        bacbo.tick()
        if modo in (MODO_AUTO, MODO_SIM):
            # cabeçalho e controles dentro do fragmento: o status acompanha a leitura em tempo real
            _cabecalho_bacbo(st, bacbo, modo, tem_playwright)
            if modo == MODO_AUTO:
                _controles_auto(st, bacbo, tem_playwright, bacbo=True)
            else:
                _controles_sim_bacbo(st, bacbo)
        if modo == MODO_AUTO and tem_playwright:
            _calibracao(st, bacbo, bacbo=True)
        motor = bacbo.motor
        st.markdown(HtmlBacBo.cartoes(motor), unsafe_allow_html=True)
        st.markdown(HtmlBacBo.faixa(motor.historico), unsafe_allow_html=True)
        if motor.pendentes:
            st.markdown(HtmlBacBo.alertas(motor), unsafe_allow_html=True)
        else:
            st.markdown(HtmlBacBo.sem_alerta(motor, bacbo.padroes), unsafe_allow_html=True)
        esquerda, direita = st.columns([1, 1.4])
        esquerda.markdown(HtmlBacBo.feed(motor), unsafe_allow_html=True)
        direita.markdown(HtmlBacBo.tabela(motor.banca, bacbo.padroes), unsafe_allow_html=True)
        st.markdown(Html.grafico_curva(motor.curva, "Banca da sessão", "rodadas", HtmlBacBo.PREVISTO),
                    unsafe_allow_html=True)

    st.fragment(painel_bacbo, run_every=1.0 if ao_vivo else None)()


def _clicar_bacbo(bacbo: SessaoBacBo, lado: str) -> None:
    """Clique em Player/Banker/Empate. Roda antes da tela ser redesenhada (callback do Streamlit)."""
    import streamlit as st

    escolha = st.session_state.get("bb_soma", SEM_SOMA)
    soma = None if escolha in (None, SEM_SOMA) else int(escolha)
    if soma == 2 and lado != EMPATE:
        st.session_state["bb_erro"] = "Soma 2 só acontece no empate (1+1 contra 1+1). Confira e clique de novo."
        return
    with bacbo.trava:
        bacbo.motor.processar(RodadaBacBo.do_resultado(lado, soma), permitir_desfazer=True)
    st.session_state["bb_soma"] = SEM_SOMA  # volta para "Não sei" e não contamina a próxima rodada


def _tela_manual_bacbo(st, bacbo: SessaoBacBo) -> None:
    """Botões de quem ganhou a rodada, com a soma dos dados opcional."""
    with st.expander("Carregar as últimas rodadas que a mesa já mostra"):
        c1, c2 = st.columns([4, 1])
        texto = c1.text_input("Do mais recente para o mais antigo: P (Player), B (Banker) ou E (Empate)",
                              key="bb_hist", placeholder="ex.: P B B E P")
        if c2.button("Carregar", key="bb_carregar"):
            letras = [c for c in texto.upper() if c not in " ,;-"]
            if not letras or any(c not in "PBE" for c in letras):
                st.error("Use só as letras P (Player), B (Banker) e E (Empate).")
            else:
                with bacbo.trava:
                    _carregar_historico_bacbo(bacbo.motor, [RodadaBacBo.do_resultado(c) for c in reversed(letras)])

    st.markdown('<div class="rr-sub">Clique em quem ganhou a rodada</div>', unsafe_allow_html=True)
    c1, c2, c3, c4 = st.columns([2, 2, 2, 2])
    for coluna, (lado, chave) in zip((c1, c2, c3), ((PLAYER, "bb_p"), (BANKER, "bb_b"), (EMPATE, "bb_e"))):
        coluna.button(NOMES_LADO[lado], key=chave, on_click=_clicar_bacbo, args=(bacbo, lado))
    c4.selectbox("Soma dos dados de quem ganhou (opcional)", [SEM_SOMA] + [str(s) for s in range(2, 13)], key="bb_soma",
                 help="Só muda o pagamento do empate (de 4:1 a 88:1). Sem a soma, o painel usa 4:1, o menor.")
    erro = st.session_state.pop("bb_erro", None)
    if erro:
        st.error(erro)
    c1, _ = st.columns([1, 5])
    if c1.button("Desfazer última", key="bb_desfazer"):
        with bacbo.trava:
            if not bacbo.motor.desfazer():
                st.warning("Nada para desfazer (dá para desfazer só a última rodada, uma vez).")


def _controles_sim_bacbo(st, bacbo: SessaoBacBo) -> None:
    c1, c2, c3 = st.columns([2, 2, 1])
    velocidade = c1.radio("Velocidade", ["Normal (15 a 20 s)", "Acelerado (1 s)"], key="bb_vel", horizontal=True)
    semente = c2.number_input("Semente (0 = aleatória)", min_value=0, max_value=10**9, value=0, step=1, key="bb_sem")
    if bacbo.sim["rodando"]:
        if c3.button("Pausar", key="bb_pau_sim"):
            bacbo.sim["rodando"] = False
            st.rerun()
    elif c3.button("Iniciar", key="bb_ini_sim", type="primary"):
        bacbo.iniciar_sim(velocidade.startswith("Acelerado"), int(semente) or None)
        st.rerun()


def _tela_backtest_bacbo(st, bacbo: SessaoBacBo, config_tela: ConfigBacBo, demonstracao=None) -> None:
    """Backtest do Bac Bo com os padrões ligados e os ajustes da barra lateral."""
    c1, c2, c3 = st.columns([2, 2, 1])
    rodadas = c1.number_input("Rodadas", min_value=1000, max_value=5_000_000, value=1_000_000, step=100_000, key="bb_bt_rod")
    semente = c2.number_input("Semente", min_value=0, max_value=10**9, value=42, step=1, key="bb_bt_sem")
    if c3.button("Rodar backtest", key="bb_bt_rodar", type="primary"):
        if not bacbo.padroes:
            st.error("Nenhum padrão ligado. Escolha os padrões em “Padrões do Bac Bo”, na barra lateral.")
        else:
            barra = st.progress(0.0, text="Simulando...")
            inicio = time.time()
            motor = executar_backtest_bacbo(int(rodadas), int(semente), config_tela, list(bacbo.padroes),
                                            ao_progredir=lambda f: barra.progress(min(1.0, f), text=f"Simulando... {f * 100:.0f}%"))
            barra.empty()
            bacbo.backtest = {"rodadas": int(rodadas), "semente": int(semente), "motor": motor,
                              "padroes": list(bacbo.padroes), "segundos": time.time() - inicio,
                              "padrao": config_tela == ConfigBacBo() and bacbo.padroes_sao_os_prontos()}

    resultado = bacbo.backtest
    if not resultado and demonstracao is not None:
        resultado = demonstracao()  # versão hospedada: mostra o teste de aceitação já pronto
    if not resultado:
        st.markdown('<div class="rr-calmo"><div><b>Rode um backtest</b><br><span>1.000.000 de rodadas com semente 42, '
                    'os 6 padrões prontos e os ajustes padrão é o teste de aceitação: tem que dar 592.519 sinais '
                    'e −R$ 113.722,00.</span></div></div>', unsafe_allow_html=True)
        return
    if resultado.get("demonstracao"):
        st.caption("Demonstração com os 6 padrões prontos e os ajustes padrão. Rode o seu backtest para testar "
                   "os padrões que você ligou ou cadastrou.")
    motor: MotorBacBo = resultado["motor"]
    total = motor.banca.total()
    st.markdown('<div class="rr-cartoes">' + "".join([
        Html.cartao("Rodadas simuladas", formatar_inteiro(resultado["rodadas"]),
                    f'semente {resultado["semente"]} · {resultado["segundos"]:.1f} s'),
        Html.cartao("Sinais conferidos", formatar_inteiro(total.sinais),
                    f'<span class="rr-pos">{formatar_inteiro(total.greens)} GREEN</span> · '
                    f'<span class="rr-neg">{formatar_inteiro(total.losses)} LOSS</span>'),
        Html.cartao("Resultado real", formatar_reais(total.lucro, com_sinal=True),
                    (f"{total.lucro / total.apostado * 100:.2f}%".replace(".", ",") + " do total apostado")
                    if total.apostado else "nenhum sinal disparado",
                    "rr-pos" if total.lucro > 0 else "rr-neg"),
        Html.cartao("Esperado pela matemática", formatar_reais(motor.banca.esperado(), com_sinal=True),
                    "1,13% em Player/Banker · 4,48% no empate"),
    ]) + "</div>", unsafe_allow_html=True)
    if resultado["rodadas"] == 1_000_000 and resultado["semente"] == 42 and resultado["padrao"]:
        bateu = total.sinais == 592_519 and round(total.lucro, 2) == -113_722.0
        st.markdown(f'<div class="rr-selo {"ok" if bateu else "nao"}">'
                    f'{"Teste de aceitação: bateu" if bateu else "Teste de aceitação: NÃO bateu"} · '
                    f'{formatar_inteiro(total.sinais)} sinais · {formatar_reais(total.lucro, com_sinal=True)}</div>',
                    unsafe_allow_html=True)
    st.markdown(Html.grafico_curva(motor.curva, "Banca no backtest", "rodadas", HtmlBacBo.PREVISTO), unsafe_allow_html=True)
    st.markdown(HtmlBacBo.tabela(motor.banca, resultado["padroes"], "Desempenho por padrão no backtest"),
                unsafe_allow_html=True)


def rodando_no_streamlit() -> bool:
    """True quando o arquivo foi aberto com 'streamlit run' (e não com 'python')."""
    if "streamlit" not in sys.modules:
        return False
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        try:
            return get_script_run_ctx(suppress_warning=True) is not None
        except TypeError:  # versões antigas não têm o parâmetro
            return get_script_run_ctx() is not None
    except Exception:
        return False


if __name__ == "__main__":
    if rodando_no_streamlit():
        app_web()  # streamlit run robo_roleta.py
    else:
        try:
            main()  # python robo_roleta.py
        except KeyboardInterrupt:
            exibir("\nEncerrado.")
