#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
===================================================================================
  ROBÔ DE ANÁLISE DE SINAIS DE ROLETA (Roleta Europeia), execução 100% local
===================================================================================

O QUE ESTE SCRIPT FAZ
  ATUALIZAÇÃO 2.0: a área Pesquisa e validação testa 19 hipóteses de roleta e
  15 de Bac Bo em períodos separados, sem garantia de acerto ou lucro futuro.
  Os padrões originais continuam abaixo para compatibilidade dos backtests.
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
import csv
import html
import hashlib
from functools import lru_cache
from itertools import product
from statistics import NormalDist
import importlib.util
import io
import json
import math
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
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
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
        if any(not math.isfinite(v) for v in (self.intervalo_min, self.intervalo_max,
                self.banca_inicial, self.valor_por_alvo, self.valor_protecao_zero)):
            raise ValueError("os valores da configuração precisam ser finitos.")
        if self.banca_inicial <= 0:
            raise ValueError("a banca inicial precisa ser positiva.")
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
    parser.add_argument("--pesquisa", metavar="CSV", help="valida padrões no histórico completo da mesa")
    parser.add_argument("--pesquisa-simulada", type=int, metavar="N", help="pesquisa com N rodadas de controle simulado")
    parser.add_argument("--relatorio-pesquisa", metavar="JSON", help="destino do relatório detalhado de pesquisa")
    parser.add_argument("--ficha-pesquisa", type=float, default=10.0, help="ficha fixa por alvo na pesquisa")
    parser.add_argument("--protecao-pesquisa", type=float, default=0.0, help="valor de proteção na pesquisa")
    parser.add_argument("--banca-pesquisa", type=float, default=1000.0, help="banca do acompanhamento de pesquisa")
    parser.add_argument("--min-sinais-pesquisa", type=int, default=200, help="mínimo de sinais por período reservado")
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
    if args.pesquisa or args.pesquisa_simulada is not None:
        try:
            rodar_pesquisa_terminal(args)
        except (ValueError, OSError) as erro:
            exibir(f"Configuração/dados inválidos: {erro}")
            sys.exit(1)
        return
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

    LIMITE_FEED = 5000     # quantos resultados guardar (tela e botão Salvar sessão)
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
        iniciar_registro_pesquisa(self, "roleta")

    def carregar_historico(self, numeros: List[int]) -> None:
        """Números que a mesa já mostrava (do mais antigo para o mais novo), sem apostar."""
        for numero in numeros:
            self.historico.append(Giro.a_partir_do_numero(numero))
        self.pendentes = self.estrategia.analisar(self.historico, self.total_giros)
        sincronizar_historico_pesquisa(self)

    def processar(self, numero: int, permitir_desfazer: bool = False) -> Tuple[Giro, List[ResultadoAposta]]:
        """Um giro completo, na mesma ordem do terminal. Devolve o giro e os resultados."""
        giro = Giro.a_partir_do_numero(numero)  # valida ANTES de mexer em qualquer coisa
        if permitir_desfazer:
            salvar_foto_pesquisa(self)
            self._foto = (copy.deepcopy(self.banca), self.historico.copy(), list(self.pendentes),
                          self.total_giros, list(self.resultados), list(self.curva))
        if not permitir_desfazer:
            self._foto = None
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
        registrar_rodada_pesquisa(self, giro, self.total_giros)
        return giro, resultados

    def desfazer(self) -> bool:
        """Volta para antes do último número (só uma vez). Devolve False se não havia o que desfazer."""
        if self._foto is None:
            return False
        banca, historico, pendentes, total, resultados, curva = self._foto
        self.banca, self.historico, self.pendentes, self.total_giros = banca, historico, pendentes, total
        self.resultados = deque(resultados, maxlen=self.LIMITE_FEED)
        self.curva = curva
        desfazer_registro_pesquisa(self)
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


URL_MESA_PADRAO = {"roleta": "https://oibet05.bar/game/immersive-roulette-by-evolution",
                   "bacbo": "https://oibet05.bar/game/bac-bo-by-evolution"}
CONFIG_PAINEL_PADRAO = {"url": "", "escondido": False, "auto_confirmar": True, "iniciar_sozinho": False,
                        "bacbo_padroes_desligados": [], "bacbo_padroes_extras": "",
                        "bacbo_url": "", "bacbo_escondido": False, "bacbo_auto_confirmar": True,
                        "bacbo_regra": "longo", "banca_roleta": 1000.0, "banca_bacbo": 1000.0}


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
        """Zera a banca e o placar; os números que já saíram continuam no histórico."""
        with self.trava:
            numeros = [g.numero for g in self.motor.historico]
            self.config = config
            self.motor = MotorWeb(config)
            if numeros:
                self.motor.carregar_historico(numeros)

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

    CORES = {"bg": "#080e0c", "surface": "#111b17", "surface2": "#19261f", "line": "#2a3930",
             "ink": "#f0ede4", "ink2": "#adb7ad", "muted": "#91a193", "red": "#a63a45",
             "black": "#141918", "green": "#5fa67a", "blue": "#7da4d4", "gold": "#cfb37c",
             "good": "#7cceaa", "bad": "#e58b8b", "player": "#658bb6"}

    @classmethod
    def css(cls) -> str:
        c = cls.CORES
        regras = [
            f":root{{--rr-bg:{c['bg']};--rr-surface:{c['surface']};--rr-surface2:{c['surface2']};--rr-line:{c['line']};"
            f"--rr-ink:{c['ink']};--rr-ink2:{c['ink2']};--rr-muted:{c['muted']};--rr-red:{c['red']};--rr-black:{c['black']};"
            f"--rr-green:{c['green']};--rr-blue:{c['blue']};--rr-gold:{c['gold']};--rr-good:{c['good']};--rr-bad:{c['bad']};"
            "--rr-display:'Bricolage Grotesque','Segoe UI',system-ui,sans-serif;--rr-mono:'JetBrains Mono',ui-monospace,Consolas,monospace;}",
            # força o escuro mesmo se o Streamlit estiver no tema claro
            ".stApp,[data-testid='stAppViewContainer']{background:radial-gradient(1200px 600px at 75% -10%,rgba(255,45,75,.08),transparent 60%),"
            "url(\"data:image/svg+xml,%3Csvg%20xmlns=%22http://www.w3.org/2000/svg%22%20viewBox=%220%200%201600%20420%22%20preserveAspectRatio=%22none%22%3E%3Cdefs%3E%3ClinearGradient%20id=%22g%22%20gradientUnits=%22userSpaceOnUse%22%20x1=%220%22%20y1=%220%22%20x2=%220%22%20y2=%22420%22%3E%3Cstop%20offset=%220%22%20stop-color=%22%233d8bff%22%20stop-opacity=%220%22/%3E%3Cstop%20offset=%221%22%20stop-color=%22%233d8bff%22%20stop-opacity=%22.2%22/%3E%3C/linearGradient%3E%3C/defs%3E%3Cg%20stroke=%22url%28%23g%29%22%20stroke-width=%221.2%22%20fill=%22none%22%3E%3Cline%20x1=%22512.0%22%20y1=%220%22%20x2=%22-1600%22%20y2=%22420%22/%3E%3Cline%20x1=%22524.0%22%20y1=%220%22%20x2=%22-1500%22%20y2=%22420%22/%3E%3Cline%20x1=%22536.0%22%20y1=%220%22%20x2=%22-1400%22%20y2=%22420%22/%3E%3Cline%20x1=%22548.0%22%20y1=%220%22%20x2=%22-1300%22%20y2=%22420%22/%3E%3Cline%20x1=%22560.0%22%20y1=%220%22%20x2=%22-1200%22%20y2=%22420%22/%3E%3Cline%20x1=%22572.0%22%20y1=%220%22%20x2=%22-1100%22%20y2=%22420%22/%3E%3Cline%20x1=%22584.0%22%20y1=%220%22%20x2=%22-1000%22%20y2=%22420%22/%3E%3Cline%20x1=%22596.0%22%20y1=%220%22%20x2=%22-900%22%20y2=%22420%22/%3E%3Cline%20x1=%22608.0%22%20y1=%220%22%20x2=%22-800%22%20y2=%22420%22/%3E%3Cline%20x1=%22620.0%22%20y1=%220%22%20x2=%22-700%22%20y2=%22420%22/%3E%3Cline%20x1=%22632.0%22%20y1=%220%22%20x2=%22-600%22%20y2=%22420%22/%3E%3Cline%20x1=%22644.0%22%20y1=%220%22%20x2=%22-500%22%20y2=%22420%22/%3E%3Cline%20x1=%22656.0%22%20y1=%220%22%20x2=%22-400%22%20y2=%22420%22/%3E%3Cline%20x1=%22668.0%22%20y1=%220%22%20x2=%22-300%22%20y2=%22420%22/%3E%3Cline%20x1=%22680.0%22%20y1=%220%22%20x2=%22-200%22%20y2=%22420%22/%3E%3Cline%20x1=%22692.0%22%20y1=%220%22%20x2=%22-100%22%20y2=%22420%22/%3E%3Cline%20x1=%22704.0%22%20y1=%220%22%20x2=%220%22%20y2=%22420%22/%3E%3Cline%20x1=%22716.0%22%20y1=%220%22%20x2=%22100%22%20y2=%22420%22/%3E%3Cline%20x1=%22728.0%22%20y1=%220%22%20x2=%22200%22%20y2=%22420%22/%3E%3Cline%20x1=%22740.0%22%20y1=%220%22%20x2=%22300%22%20y2=%22420%22/%3E%3Cline%20x1=%22752.0%22%20y1=%220%22%20x2=%22400%22%20y2=%22420%22/%3E%3Cline%20x1=%22764.0%22%20y1=%220%22%20x2=%22500%22%20y2=%22420%22/%3E%3Cline%20x1=%22776.0%22%20y1=%220%22%20x2=%22600%22%20y2=%22420%22/%3E%3Cline%20x1=%22788.0%22%20y1=%220%22%20x2=%22700%22%20y2=%22420%22/%3E%3Cline%20x1=%22800.0%22%20y1=%220%22%20x2=%22800%22%20y2=%22420%22/%3E%3Cline%20x1=%22812.0%22%20y1=%220%22%20x2=%22900%22%20y2=%22420%22/%3E%3Cline%20x1=%22824.0%22%20y1=%220%22%20x2=%221000%22%20y2=%22420%22/%3E%3Cline%20x1=%22836.0%22%20y1=%220%22%20x2=%221100%22%20y2=%22420%22/%3E%3Cline%20x1=%22848.0%22%20y1=%220%22%20x2=%221200%22%20y2=%22420%22/%3E%3Cline%20x1=%22860.0%22%20y1=%220%22%20x2=%221300%22%20y2=%22420%22/%3E%3Cline%20x1=%22872.0%22%20y1=%220%22%20x2=%221400%22%20y2=%22420%22/%3E%3Cline%20x1=%22884.0%22%20y1=%220%22%20x2=%221500%22%20y2=%22420%22/%3E%3Cline%20x1=%22896.0%22%20y1=%220%22%20x2=%221600%22%20y2=%22420%22/%3E%3Cline%20x1=%22908.0%22%20y1=%220%22%20x2=%221700%22%20y2=%22420%22/%3E%3Cline%20x1=%22920.0%22%20y1=%220%22%20x2=%221800%22%20y2=%22420%22/%3E%3Cline%20x1=%22932.0%22%20y1=%220%22%20x2=%221900%22%20y2=%22420%22/%3E%3Cline%20x1=%22944.0%22%20y1=%220%22%20x2=%222000%22%20y2=%22420%22/%3E%3Cline%20x1=%22956.0%22%20y1=%220%22%20x2=%222100%22%20y2=%22420%22/%3E%3Cline%20x1=%22968.0%22%20y1=%220%22%20x2=%222200%22%20y2=%22420%22/%3E%3Cline%20x1=%22980.0%22%20y1=%220%22%20x2=%222300%22%20y2=%22420%22/%3E%3Cline%20x1=%22992.0%22%20y1=%220%22%20x2=%222400%22%20y2=%22420%22/%3E%3Cline%20x1=%221004.0%22%20y1=%220%22%20x2=%222500%22%20y2=%22420%22/%3E%3Cline%20x1=%221016.0%22%20y1=%220%22%20x2=%222600%22%20y2=%22420%22/%3E%3Cline%20x1=%221028.0%22%20y1=%220%22%20x2=%222700%22%20y2=%22420%22/%3E%3Cline%20x1=%221040.0%22%20y1=%220%22%20x2=%222800%22%20y2=%22420%22/%3E%3Cline%20x1=%221052.0%22%20y1=%220%22%20x2=%222900%22%20y2=%22420%22/%3E%3Cline%20x1=%221064.0%22%20y1=%220%22%20x2=%223000%22%20y2=%22420%22/%3E%3Cline%20x1=%221076.0%22%20y1=%220%22%20x2=%223100%22%20y2=%22420%22/%3E%3Cline%20x1=%221088.0%22%20y1=%220%22%20x2=%223200%22%20y2=%22420%22/%3E%3Cline%20x1=%22-1600%22%20y1=%221.5%22%20x2=%223200%22%20y2=%221.5%22/%3E%3Cline%20x1=%22-1600%22%20y1=%226.8%22%20x2=%223200%22%20y2=%226.8%22/%3E%3Cline%20x1=%22-1600%22%20y1=%2216.7%22%20x2=%223200%22%20y2=%2216.7%22/%3E%3Cline%20x1=%22-1600%22%20y1=%2231.4%22%20x2=%223200%22%20y2=%2231.4%22/%3E%3Cline%20x1=%22-1600%22%20y1=%2251.3%22%20x2=%223200%22%20y2=%2251.3%22/%3E%3Cline%20x1=%22-1600%22%20y1=%2276.6%22%20x2=%223200%22%20y2=%2276.6%22/%3E%3Cline%20x1=%22-1600%22%20y1=%22107.6%22%20x2=%223200%22%20y2=%22107.6%22/%3E%3Cline%20x1=%22-1600%22%20y1=%22144.3%22%20x2=%223200%22%20y2=%22144.3%22/%3E%3Cline%20x1=%22-1600%22%20y1=%22187.0%22%20x2=%223200%22%20y2=%22187.0%22/%3E%3Cline%20x1=%22-1600%22%20y1=%22235.8%22%20x2=%223200%22%20y2=%22235.8%22/%3E%3Cline%20x1=%22-1600%22%20y1=%22290.8%22%20x2=%223200%22%20y2=%22290.8%22/%3E%3Cline%20x1=%22-1600%22%20y1=%22352.2%22%20x2=%223200%22%20y2=%22352.2%22/%3E%3Cline%20x1=%22-1600%22%20y1=%22420.0%22%20x2=%223200%22%20y2=%22420.0%22/%3E%3C/g%3E%3C/svg%3E\") center bottom/100% 46vh no-repeat fixed,"
            "radial-gradient(900px 380px at 50% 105%,rgba(61,139,255,.10),transparent 70%) fixed,var(--rr-bg)!important;color:var(--rr-ink);}",
            "[data-testid='stHeader']{background:transparent!important;}",
            "[data-testid='stSidebar']{background:#0f1218!important;border-right:1px solid var(--rr-line);}",
            ".stApp label,.stApp [data-testid='stMarkdownContainer']>p{color:var(--rr-ink);}",
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
            ".rr-titulo{font-family:var(--rr-display);font-weight:800;font-size:2.1rem;letter-spacing:-.03em;line-height:1;margin:0;color:var(--rr-ink);"
            "text-shadow:0 1px 0 #b9bec9,0 2px 0 #8a909c,0 3px 0 #5d636e,0 4px 0 #3c414b,0 9px 14px rgba(0,0,0,.75);}",
            ".rr-sub{font-family:var(--rr-mono);font-size:.72rem;letter-spacing:.12em;text-transform:uppercase;color:var(--rr-muted);margin-bottom:6px;}",
            ".rr-status{display:inline-flex;align-items:center;gap:8px;padding:6px 12px;border-radius:999px;border:1px solid var(--rr-line);background:var(--rr-surface);font-family:var(--rr-mono);font-size:.78rem;color:var(--rr-ink2);}",
            ".rr-status i{width:8px;height:8px;border-radius:50%;background:var(--rr-muted);display:inline-block;}",
            ".rr-status.on i{background:var(--rr-green);box-shadow:0 0 0 0 rgba(20,210,122,.6);animation:rr-ping 1.6s infinite;}",
            ".rr-status.alerta i{background:var(--rr-gold);}",
            "@keyframes rr-ping{0%{box-shadow:0 0 0 0 rgba(20,210,122,.55)}80%{box-shadow:0 0 0 8px rgba(20,210,122,0)}100%{box-shadow:0 0 0 0 rgba(20,210,122,0)}}",
            # cartões
            ".rr-cartoes{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px;margin:4px 0 22px;}",
            ".rr-cartao{background:linear-gradient(160deg,#1f2534 0%,#151a25 55%,#10141c 100%);border:1px solid var(--rr-line);border-radius:14px;padding:16px 18px;display:grid;gap:6px;min-width:0;"
            "box-shadow:inset 0 1px 0 rgba(255,255,255,.08),0 5px 0 -1px #0a0d13,0 16px 26px -12px rgba(0,0,0,.9);transition:transform .25s ease,box-shadow .25s ease;}",
            ".rr-cartao:hover{transform:perspective(700px) rotateX(6deg) translateY(-3px);box-shadow:inset 0 1px 0 rgba(255,255,255,.1),0 8px 0 -1px #0a0d13,0 24px 32px -14px rgba(0,0,0,.95);}",
            ".rr-cartao .r{font-family:var(--rr-mono);font-size:.7rem;letter-spacing:.1em;text-transform:uppercase;color:var(--rr-muted);}",
            ".rr-cartao .v{font-family:var(--rr-display);font-weight:800;font-size:1.9rem;letter-spacing:-.02em;line-height:1.05;color:var(--rr-ink);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}",
            ".rr-cartao .d{font-family:var(--rr-mono);font-size:.76rem;color:var(--rr-ink2);}",
            ".rr-pos{color:var(--rr-good)!important;}.rr-neg{color:var(--rr-bad)!important;}",
            # pedras
            ".rr-bloco{background:linear-gradient(170deg,#161b26,var(--rr-surface) 60%);border:1px solid var(--rr-line);border-radius:14px;padding:16px 18px;margin-bottom:18px;"
            "box-shadow:inset 0 1px 0 rgba(255,255,255,.06),0 5px 0 -1px #0a0d13,0 18px 28px -16px rgba(0,0,0,.85);}",
            ".rr-bloco .rr-h{font-family:var(--rr-display);font-weight:800;font-size:1rem;margin:0 0 12px;color:var(--rr-ink);letter-spacing:-.01em;}",
            ".rr-bloco .rr-h small{font-family:var(--rr-mono);font-weight:400;font-size:.7rem;color:var(--rr-muted);margin-left:8px;letter-spacing:.06em;text-transform:uppercase;}",
            ".rr-pedras{display:flex;flex-wrap:wrap;gap:8px;align-items:center;}",
            ".rr-pedra{width:40px;height:40px;border-radius:50%;display:inline-grid;place-items:center;flex:none;font-family:var(--rr-mono);font-weight:700;font-size:.92rem;color:#fff;}",
            ".rr-pedra,.bb-chip{text-shadow:0 1px 2px rgba(0,0,0,.55);}",
            ".rr-pedra.v{background:radial-gradient(circle at 26% 19%,rgba(255,255,255,.9) 0,rgba(255,255,255,.3) 5%,rgba(255,255,255,0) 13%),radial-gradient(circle at 42% 38%,#ff7488 0%,#e8233f 52%,#7d0c1c 100%);box-shadow:inset -3px -5px 9px rgba(0,0,0,.42),inset 2px 3px 5px rgba(255,255,255,.16),0 6px 10px rgba(0,0,0,.6);}",
            ".rr-pedra.p{background:radial-gradient(circle at 26% 19%,rgba(255,255,255,.9) 0,rgba(255,255,255,.3) 5%,rgba(255,255,255,0) 13%),radial-gradient(circle at 42% 38%,#5a606e 0%,#262a33 52%,#07080b 100%);box-shadow:inset -3px -5px 9px rgba(0,0,0,.42),inset 2px 3px 5px rgba(255,255,255,.16),0 6px 10px rgba(0,0,0,.6);}",
            ".rr-pedra.z{background:radial-gradient(circle at 26% 19%,rgba(255,255,255,.9) 0,rgba(255,255,255,.3) 5%,rgba(255,255,255,0) 13%),radial-gradient(circle at 42% 38%,#7dffc0 0%,#12c873 52%,#05633a 100%);box-shadow:inset -3px -5px 9px rgba(0,0,0,.42),inset 2px 3px 5px rgba(255,255,255,.16),0 6px 10px rgba(0,0,0,.6);color:#04140b;text-shadow:none;}",
            ".rr-pedra.pq{width:30px;height:30px;font-size:.78rem;}",
            ".rr-pedra.nova{width:52px;height:52px;font-size:1.15rem;outline:2px solid var(--rr-ink);outline-offset:3px;animation:rr-flutua 3s ease-in-out infinite;}",
            "@keyframes rr-flutua{0%,100%{transform:translateY(0)}50%{transform:translateY(-4px)}}",
            ".rr-pedras .rot{font-family:var(--rr-mono);font-size:.68rem;color:var(--rr-muted);letter-spacing:.08em;text-transform:uppercase;}",
            # alertas
            ".rr-alerta{position:relative;border-radius:16px;padding:20px 22px;margin-bottom:16px;background:linear-gradient(135deg,rgba(255,45,75,.12),rgba(19,23,32,.95) 45%);border:1px solid var(--rr-red);animation:rr-brilho 2.2s ease-in-out infinite;}",
            "@keyframes rr-brilho{0%,100%{box-shadow:inset 0 1px 0 rgba(255,255,255,.08),0 6px 0 -1px #3a0a14,0 0 0 1px rgba(255,45,75,.6),0 0 22px rgba(255,45,75,.25)}"
            "50%{box-shadow:inset 0 1px 0 rgba(255,255,255,.08),0 6px 0 -1px #3a0a14,0 0 0 1px rgba(255,45,75,.9),0 0 38px rgba(255,45,75,.5)}}",
            ".rr-alerta .tag{font-family:var(--rr-mono);font-size:.72rem;letter-spacing:.14em;text-transform:uppercase;color:var(--rr-red);font-weight:700;}",
            ".rr-alerta .pad{font-family:var(--rr-display);font-weight:800;font-size:1.25rem;margin:4px 0 12px;color:var(--rr-ink);}",
            ".rr-alerta .grade{display:grid;grid-template-columns:minmax(0,1.4fr) minmax(0,1fr) minmax(0,1fr);gap:16px;align-items:start;}",
            ".rr-alerta .lbl{font-family:var(--rr-mono);font-size:.68rem;letter-spacing:.1em;text-transform:uppercase;color:var(--rr-muted);margin-bottom:6px;}",
            ".rr-alvos{display:flex;flex-wrap:wrap;gap:8px;}",
            ".rr-alvo{display:inline-flex;align-items:center;gap:10px;padding:10px 14px;border-radius:12px;background:var(--rr-surface2);border:1px solid var(--rr-line);font-family:var(--rr-display);font-weight:800;font-size:1.15rem;color:var(--rr-ink);}",
            ".rr-alvo small{font-family:var(--rr-mono);font-weight:400;font-size:.72rem;color:var(--rr-ink2);}",
            ".rr-alvo .sw{width:22px;height:22px;border-radius:50%;display:inline-block;background-image:radial-gradient(circle at 33% 28%,rgba(255,255,255,.85) 0,rgba(255,255,255,0) 30%)!important;"
            "box-shadow:inset -2px -3px 5px rgba(0,0,0,.45),0 3px 6px rgba(0,0,0,.5);}",
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
            ".rr-marca i{width:16px;height:16px;border-radius:50%;background:radial-gradient(circle at 33% 28%,rgba(255,255,255,.8) 0,rgba(255,255,255,0) 35%),conic-gradient(var(--rr-red) 0 33%,var(--rr-black) 0 66%,var(--rr-green) 0);box-shadow:inset -2px -2px 4px rgba(0,0,0,.5),0 3px 8px rgba(0,0,0,.6);display:inline-block;}",
            # Bac Bo: pedras azul (Player), vermelha (Banker) e dourada (Empate), com a soma vencedora
            ".bb-chip{width:40px;height:40px;border-radius:50%;display:inline-flex;flex-direction:column;align-items:center;justify-content:center;flex:none;font-family:var(--rr-mono);font-weight:700;font-size:.95rem;line-height:1;color:#fff;}",
            ".stApp .bb-chip small,.bb-chip small{font-size:.6rem;font-weight:600;opacity:.9;margin-top:2px;color:inherit!important;}",
            ".bb-chip.p{background:radial-gradient(circle at 26% 19%,rgba(255,255,255,.9) 0,rgba(255,255,255,.3) 5%,rgba(255,255,255,0) 13%),radial-gradient(circle at 42% 38%,#9dbcff 0%,#2f6fff 52%,#0f2c85 100%);box-shadow:inset -3px -5px 9px rgba(0,0,0,.42),inset 2px 3px 5px rgba(255,255,255,.16),0 6px 10px rgba(0,0,0,.6);}",
            ".bb-chip.b{background:radial-gradient(circle at 26% 19%,rgba(255,255,255,.9) 0,rgba(255,255,255,.3) 5%,rgba(255,255,255,0) 13%),radial-gradient(circle at 42% 38%,#ff7488 0%,#e8233f 52%,#7d0c1c 100%);box-shadow:inset -3px -5px 9px rgba(0,0,0,.42),inset 2px 3px 5px rgba(255,255,255,.16),0 6px 10px rgba(0,0,0,.6);}",
            ".bb-chip.e{background:radial-gradient(circle at 26% 19%,rgba(255,255,255,.9) 0,rgba(255,255,255,.3) 5%,rgba(255,255,255,0) 13%),radial-gradient(circle at 42% 38%,#fff1c4 0%,#e8b84a 52%,#7f5a0f 100%);box-shadow:inset -3px -5px 9px rgba(0,0,0,.42),inset 2px 3px 5px rgba(255,255,255,.16),0 6px 10px rgba(0,0,0,.6);color:#1a1300;text-shadow:0 1px 0 rgba(255,255,255,.35);}",
            ".bb-chip.pq{width:30px;height:30px;font-size:.78rem;}.bb-chip.pq small{display:none;}",
            ".bb-chip.nova{width:52px;height:52px;font-size:1.15rem;outline:2px solid var(--rr-ink);outline-offset:3px;animation:rr-flutua 3s ease-in-out infinite;}",
            f".rr-marca.bb i{{background:radial-gradient(circle at 33% 28%,rgba(255,255,255,.8) 0,rgba(255,255,255,0) 35%),conic-gradient({c['player']} 0 45%,var(--rr-red) 0 90%,var(--rr-gold) 0);}}",
            ".st-key-bb_p button,.st-key-bb_b button,.st-key-bb_e button{width:100%;min-height:64px;border:0!important;}",
            ".st-key-bb_p button p,.st-key-bb_b button p,.st-key-bb_e button p{font-family:var(--rr-display)!important;font-weight:800!important;font-size:1.15rem!important;letter-spacing:.04em;color:#fff!important;}",
            f".st-key-bb_p button{{background:linear-gradient(180deg,#5a8cff,{c['player']})!important;box-shadow:0 6px 0 #173a9a,0 12px 18px rgba(0,0,0,.45)!important;}}",
            ".st-key-bb_b button{background:linear-gradient(180deg,#ff5a72,var(--rr-red))!important;box-shadow:0 6px 0 #8c1426,0 12px 18px rgba(0,0,0,.45)!important;}",
            ".st-key-bb_e button{background:linear-gradient(180deg,#ffd987,var(--rr-gold))!important;box-shadow:0 6px 0 #8a6414,0 12px 18px rgba(0,0,0,.45)!important;}.st-key-bb_e button p{color:#1a1300!important;}",
            ".st-key-bb_p button,.st-key-bb_b button,.st-key-bb_e button{transition:transform .08s ease,box-shadow .08s ease;}",
            ".st-key-bb_p button:active,.st-key-bb_b button:active,.st-key-bb_e button:active{transform:translateY(5px);box-shadow:0 1px 0 rgba(0,0,0,.6)!important;}",
            ".rr-aviso{font-family:var(--rr-mono);font-size:.78rem;color:var(--rr-gold);margin:-6px 0 14px;}",
            "@media (max-width:900px){.rr-cartoes{grid-template-columns:repeat(2,minmax(0,1fr));}.rr-alerta .grade{grid-template-columns:1fr;}}",
            "@media (max-width:520px){.rr-cartao{padding:14px;}.rr-cartao .v{font-size:1.3rem;white-space:normal;overflow:visible;}}",
            "@media (prefers-reduced-motion:reduce){.rr-alerta,.rr-status.on i,.rr-pedra.nova,.bb-chip.nova{animation:none;}.rr-cartao{transition:none;}}",
        ]
        # tabuleiro do modo manual: cada botão com a cor do número (classe st-key-<key> do Streamlit)
        for n in range(37):
            cor, borda = {"v": (c["red"], "#7d0c1c"), "p": ("#2a2e38", "#07080b"), "z": ("#0fb868", "#05633a")}[cls.tipo_cor(n)]
            regras.append(f".st-key-rr_num_{n} button{{background:linear-gradient(180deg,rgba(255,255,255,.14),rgba(255,255,255,0) 60%),{cor}!important;"
                          f"color:#fff!important;border:0!important;min-height:44px;font-family:var(--rr-mono);font-weight:700;"
                          f"box-shadow:0 4px 0 {borda},0 8px 12px rgba(0,0,0,.45)!important;transition:transform .08s ease;}}"
                          f".st-key-rr_num_{n} button:active{{transform:translateY(3px);box-shadow:0 1px 0 {borda}!important;}}")
        regras.append(_css_visual_realista())
        regras.append(_css_lobby_e_som())  # materiais e elementos 3D do lobby
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
            cls.cartao("Banca", formatar_reais(banca.saldo),
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
                f'</div><div class="rr-validade">Vale só para o próximo giro. O painel confere sozinho e lança na banca.</div></div>')

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
        legenda = (f'<div class="rr-legenda"><span><i style="background:{Html.CORES["blue"]}"></i>Banca (resultado acumulado)</span>'
                   f'<span><i style="background:#8b93a3"></i>{html.escape(previsto)}</span></div>')
        return f'<div class="rr-bloco rr-graf"><div class="rr-h">{titulo}</div>{legenda}{"".join(partes)}</div>'


MODO_AUTO, MODO_MANUAL = "Mesa real (automática)", "Mesa real (manual)"
MODO_SIM, MODO_BACKTEST = "Simulador ao vivo", "Backtest em massa"


def app_web() -> None:
    """A tela do painel. O Streamlit executa esta função de novo a cada interação."""
    import streamlit as st

    st.set_page_config(page_title="Roleta e Bac Bo · Análise", page_icon="🎯", layout="wide",
                       initial_sidebar_state="auto")
    st.markdown(Html.css(), unsafe_allow_html=True)
    if not hasattr(st, "fragment"):
        st.error("Este painel precisa do Streamlit 1.37 ou mais novo. Rode:  py -m pip install -U streamlit")
        st.stop()

    # No seu PC (aberto pelo atalho/opção 6) existe UM painel só, que continua vivo se você
    # recarregar a página. Hospedado na internet, cada visitante ganha o próprio painel.
    no_meu_pc = os.environ.get("ROBO_ROLETA_LOCAL") == "1"

    @st.cache_resource
    def obter_sessao() -> SessaoWeb:
        sessao = SessaoWeb()
        sessao.nova_sessao(_config_salva("roleta"))  # banca e entrada que você deixou salvas
        return sessao

    if no_meu_pc:
        sessao = obter_sessao()
    else:
        if "rr_sessao" not in st.session_state:
            st.session_state["rr_sessao"] = SessaoWeb()
        sessao = st.session_state["rr_sessao"]

    # --------------------------- lobby ou painel -----------------------------------
    no_lobby = _tela_inicial(st, sessao, no_meu_pc) == "lobby"
    jogo = st.session_state.get("rr_jogo_escolhido", JOGO_ROLETA)
    e_bacbo = jogo == JOGO_BACBO
    bacbo = obter_bacbo(sessao, no_meu_pc) if e_bacbo and not no_lobby else None
    modo, config_tela = MODO_AUTO, None

    # --------------------------- barra lateral -------------------------------------
    with st.sidebar:
        if no_lobby:
            st.markdown('<div class="rr-marca lb"><i></i>Mesa de análise</div>'
                        '<div class="rr-sub">Roleta · Bac Bo</div>', unsafe_allow_html=True)
        else:
            sub = ("Bac Bo (Evolution)" if e_bacbo else "Roleta europeia") + ("" if no_meu_pc else " · banca fictícia")
            st.markdown(f'<div class="rr-marca{" bb" if e_bacbo else ""}"><i></i>'
                        f'{"Robô de Bac Bo" if e_bacbo else "Robô de Roleta"}</div><div class="rr-sub">{sub}</div>',
                        unsafe_allow_html=True)
            st.button("◀  Voltar ao lobby", key="rr_lobby", on_click=_ir_para_lobby)
        if no_lobby:
            pass
        elif no_meu_pc:
            # No seu PC: só o jogo, a banca e o botão Entrar. A mesa é lida sozinha.
            modo = MODO_AUTO
            config_tela = _banca_lateral(st, bacbo if bacbo is not None else sessao, bacbo is not None)
            if bacbo is not None:
                _padroes_bacbo(st, bacbo)
        else:
            # Hospedado (portfólio): a leitura automática não existe, então ficam os outros modos
            modo = st.radio("Modo de operação", [MODO_AUTO, MODO_MANUAL, MODO_SIM, MODO_BACKTEST], index=3, key="rr_modo")
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
        visao = "Monitor" if no_lobby else st.radio("Área", ["Monitor", "Pesquisa e validação"], key="rr_area")
        som = {} if no_lobby else _som_lateral(st)
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

    if no_lobby:
        tela_lobby(st, sessao, no_meu_pc)
        return

    # Trocar de jogo conta como trocar de modo: pausa a leitura e o simulador (as sessões ficam guardadas)
    sessao.trocar_modo(f"{jogo} · {modo}")

    alvo_sessao = bacbo if bacbo is not None else sessao
    alvo_sessao.motor.fonte_pesquisa = ("simulado" if modo == MODO_SIM else
                                      ("manual" if modo == MODO_MANUAL else "navegador"))
    if visao == "Pesquisa e validação":
        _painel_pesquisa(st, alvo_sessao, "bacbo" if bacbo is not None else "roleta")
        return
    if bacbo is not None:
        app_bacbo(st, bacbo, modo, no_meu_pc, config_tela, som)
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
        _resumo_monitor_pesquisa(st, motor, "roleta")
        if motor.pendentes:
            st.markdown("".join(Html.alerta(s, motor) for s in motor.pendentes), unsafe_allow_html=True)
        else:
            st.markdown(Html.sem_alerta(motor), unsafe_allow_html=True)
        st.markdown(Html.feed(motor, limite=12), unsafe_allow_html=True)
        _botao_salvar(st, csv_sessao_roleta(motor), "roleta", "rr")
        st.markdown(Html.grafico_curva(motor.curva, "Banca da sessão"), unsafe_allow_html=True)
        _tocar_sons(st, _eventos_som_roleta(motor, som))

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
    url = c1.text_input("Endereço da mesa", value=cfg[c_ + "url"] or URL_MESA_PADRAO["bacbo" if bacbo else "roleta"],
                        key=f"{k}_url",
                        placeholder=f"ex.: https://site-do-cassino/game/{exemplo}")
    janela = c2.radio("Chrome do robô", ["Escondido (sem janela)", "Visível (para fazer login)"],
                      index=0 if cfg[c_ + "escondido"] else 1, key=f"{k}_janela")
    c3, c4, c5 = st.columns([2, 2, 1])
    auto = c3.checkbox("Confirmar a faixa sozinho", value=cfg[c_ + "auto_confirmar"], key=f"{k}_auto")
    sozinho = False if bacbo else c4.checkbox("Começar a ler sozinho ao entrar na roleta",
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
        if linha_mesa == 2 and colunas[0].button("0", key="rr_num_0", use_container_width=True):
            clicado = 0
        for j in range(12):
            n = 3 * j + linha_mesa
            if colunas[j + 1].button(str(n), key=f"rr_num_{n}", use_container_width=True):
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
        if any(not math.isfinite(v) for v in (self.valor_por_alvo, self.valor_protecao_empate, self.banca_inicial)):
            raise ValueError("os valores da banca precisam ser finitos.")
        if isinstance(self.tamanho_historico, bool) or not isinstance(self.tamanho_historico, int) or self.tamanho_historico < 1:
            raise ValueError("tamanho_historico precisa ser um inteiro positivo.")
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
        if any(isinstance(d, bool) or not isinstance(d, int) or not 1 <= d <= 6 for d in (p1, p2, b1, b2)):
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
        if soma is not None and (isinstance(soma, bool) or not isinstance(soma, int) or not 2 <= soma <= 12):
            raise ValueError("a soma de dois dados vai de 2 a 12")
        if soma == 2 and resultado != EMPATE:
            raise ValueError("soma vencedora 2 só é possível em empate")
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


TAMANHO_GATILHO_BACBO = {"rep3": 3, "alt4": 4, "rep2": 2, "emp": 1, "2x2": 4, "surf4": 4}


def _tamanho_gatilho(chave: str) -> int:
    """Quantas rodadas formam o gatilho (o padrão mais longo é o mais específico)."""
    if chave.startswith("c:"):
        return len(chave[2:].split(">")[0])
    return TAMANHO_GATILHO_BACBO.get(chave, 3)


# Quando os padrões da mesma rodada apontam alvos diferentes (ex.: PPBB dispara "2 iguais"
# -> BANKER e "Duplas" -> PLAYER), o robô dá UMA entrada só. Regras possíveis:
REGRA_PULAR, REGRA_MAIS_LONGO = "pular", "longo"
REGRA_PADRAO = REGRA_MAIS_LONGO
NOMES_REGRA = {REGRA_MAIS_LONGO: "Vale o padrão mais longo", REGRA_PULAR: "Não entra na rodada"}


def consolidar_sinais(brutos: List["SinalBacBo"], regra: str = REGRA_PADRAO
                      ) -> Tuple[List["SinalBacBo"], List["SinalBacBo"]]:
    """
    Junta os sinais da rodada numa entrada só. Devolve (entrada, descartados):
      - todos no mesmo alvo  -> uma entrada (os nomes dos padrões ficam juntos)
      - alvos diferentes     -> "pular": nenhuma entrada | "longo": vale o alvo do padrão
                                mais longo (se dois do mesmo tamanho discordarem, não entra)
    """
    if not brutos:
        return [], []
    alvos = {s.alvo for s in brutos}
    if len(alvos) > 1:
        if regra != REGRA_MAIS_LONGO:
            return [], list(brutos)
        maior = max(_tamanho_gatilho(s.chave) for s in brutos)
        alvos_maior = {s.alvo for s in brutos if _tamanho_gatilho(s.chave) == maior}
        if len(alvos_maior) > 1:
            return [], list(brutos)
        alvos = alvos_maior
    alvo = alvos.pop()
    juntos = [s for s in brutos if s.alvo == alvo]
    descartados = [s for s in brutos if s.alvo != alvo]
    principal = max(juntos, key=lambda s: _tamanho_gatilho(s.chave))
    nome = " + ".join(s.nome for s in sorted(juntos, key=lambda s: -_tamanho_gatilho(s.chave)))
    return [SinalBacBo(principal.chave, nome, alvo, principal.rodada_origem)], descartados


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
    """
    Duas contas, com os pagamentos reais do Bac Bo:
      - a banca: UMA entrada por rodada (a que o painel manda fazer);
      - o placar de cada padrão como se ele entrasse sozinho (para comparar os padrões).
    """

    def __init__(self, config: ConfigBacBo) -> None:
        self.config = config
        self.saldo = config.banca_inicial
        self.menor_saldo = config.banca_inicial
        self.geral = EstatisticaPadrao()               # entradas de verdade
        self.estatisticas: Dict[str, EstatisticaPadrao] = {}  # cada padrão sozinho
        self.nomes: Dict[str, str] = {}
        self.tipos: Dict[str, str] = {}
        self.apostado_lado = 0.0
        self.apostado_empate = 0.0
        self.entradas_tipo = {"lado": 0, "empate": 0}
        self.liquidacoes_estimadas = 0

    def _calcular(self, alvo: str, rodada: RodadaBacBo) -> Tuple[str, float, float, float, float]:
        """(status, total apostado, lucro, apostado no lado, apostado no empate) de uma entrada."""
        ficha = self.config.valor_por_alvo
        if alvo == EMPATE:
            acertou = rodada.resultado == EMPATE
            retorno = ficha * (1 + rodada.paga_empate) if acertou else 0.0
            return ("GREEN" if acertou else "LOSS"), ficha, retorno - ficha, 0.0, ficha
        protecao = self.config.valor_protecao_empate if self.config.protecao_empate else 0.0
        apostado = ficha + protecao
        if rodada.resultado == alvo:
            retorno, status = ficha * 2, "GREEN"
        elif rodada.resultado == EMPATE:
            retorno, status = ficha * DEVOLUCAO_NO_EMPATE + protecao * (1 + rodada.paga_empate), "EMPATE"
        else:
            retorno, status = 0.0, "LOSS"
        return status, apostado, retorno - apostado, ficha, protecao

    @staticmethod
    def _somar(est: EstatisticaPadrao, status: str, apostado: float, lucro: float) -> None:
        est.sinais += 1
        est.apostado += apostado
        est.lucro += lucro
        if status == "GREEN":
            est.greens += 1
        elif status == "EMPATE" and lucro > 0:
            est.greens_protecao += 1
        else:
            est.losses += 1

    def liquidar(self, sinal: SinalBacBo, rodada: RodadaBacBo) -> ResultadoBacBo:
        """A entrada da rodada (a única que mexe na banca)."""
        status, apostado, lucro, no_lado, no_empate = self._calcular(sinal.alvo, rodada)
        if rodada.resultado == EMPATE and rodada.soma_vencedora is None and (sinal.alvo == EMPATE or
                (self.config.protecao_empate and self.config.valor_protecao_empate > 0)):
            self.liquidacoes_estimadas += 1
        self._somar(self.geral, status, apostado, lucro)
        self.apostado_lado += no_lado
        self.apostado_empate += no_empate
        self.entradas_tipo[sinal.tipo] += 1
        self.saldo += lucro
        self.menor_saldo = min(self.menor_saldo, self.saldo)
        return ResultadoBacBo(sinal, rodada, status, apostado, lucro)

    def registrar_padrao(self, sinal: SinalBacBo, rodada: RodadaBacBo) -> None:
        """Placar do padrão como se ele entrasse sozinho (não mexe na banca)."""
        status, apostado, lucro, _, _ = self._calcular(sinal.alvo, rodada)
        self.nomes[sinal.chave], self.tipos[sinal.chave] = sinal.nome, sinal.tipo
        self._somar(self.estatisticas.setdefault(sinal.chave, EstatisticaPadrao()), status, apostado, lucro)

    def total(self) -> EstatisticaPadrao:
        return copy.copy(self.geral)

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
    """
    O mesmo ciclo do motor da roleta: registra a rodada, confere a entrada anterior e
    procura padrões. Os sinais da rodada viram UMA entrada (veja consolidar_sinais).
    """

    LIMITE_FEED = 5000
    LIMITE_CURVA = 3000

    def __init__(self, config: ConfigBacBo, padroes: Optional[List[PadraoBacBo]] = None,
                 registrar: bool = True, regra: str = REGRA_PADRAO) -> None:
        self.config = config
        self.estrategia = EstrategiaBacBo(padroes if padroes is not None else PADROES_BACBO)
        self.regra = regra
        self.banca = BancaBacBo(config)
        self.historico: Deque[RodadaBacBo] = deque(maxlen=config.tamanho_historico)
        self.brutos: List[SinalBacBo] = []      # o que cada padrão disparou
        self.pendentes: List[SinalBacBo] = []   # a entrada da próxima rodada (0 ou 1)
        self.descartados: List[SinalBacBo] = []  # sinais que discordaram e ficaram de fora
        self.puladas = 0                         # rodadas sem entrada porque os padrões discordaram
        self.total_rodadas = 0
        self.registrar = registrar
        self.resultados: Deque[ResultadoBacBo] = deque(maxlen=self.LIMITE_FEED)
        self.curva: List[Tuple[int, float, float]] = [(0, 0.0, 0.0)]
        self._foto: Optional[tuple] = None
        iniciar_registro_pesquisa(self, "bacbo")

    def reanalisar(self) -> None:
        """Procura padrões no histórico atual e monta a entrada da próxima rodada."""
        self.brutos = self.estrategia.analisar(self.historico, self.total_rodadas)
        self.pendentes, self.descartados = consolidar_sinais(self.brutos, self.regra)

    def processar(self, rodada: RodadaBacBo, permitir_desfazer: bool = False) -> List[ResultadoBacBo]:
        if permitir_desfazer:
            salvar_foto_pesquisa(self)
            self._foto = (copy.deepcopy(self.banca), self.historico.copy(), list(self.brutos), list(self.pendentes),
                          list(self.descartados), self.puladas, self.total_rodadas, list(self.resultados), list(self.curva))
        if not permitir_desfazer:
            self._foto = None
        self.total_rodadas += 1
        self.historico.append(rodada)
        if self.brutos and not self.pendentes:
            self.puladas += 1  # havia sinal, mas os padrões discordaram e a rodada ficou sem entrada
        resultados: List[ResultadoBacBo] = []
        for sinal in self.pendentes:
            try:
                resultados.append(self.banca.liquidar(sinal, rodada))
            except Exception as erro:
                exibir(f"⚠️  Erro ao validar {sinal.nome}: {erro}")
        for sinal in self.brutos:  # placar de cada padrão, mesmo os que ficaram de fora
            self.banca.registrar_padrao(sinal, rodada)
        self.reanalisar()
        if self.registrar:
            self.resultados.extend(resultados)
            self.curva.append((self.total_rodadas, self.banca.geral.lucro, self.banca.esperado()))
            if len(self.curva) > self.LIMITE_CURVA:
                self.curva = self.curva[:1] + self.curva[1:-1:2] + self.curva[-1:]
        registrar_rodada_pesquisa(self, rodada, self.total_rodadas)
        return resultados

    def desfazer(self) -> bool:
        if self._foto is None:
            return False
        (self.banca, self.historico, self.brutos, self.pendentes, self.descartados, self.puladas,
         self.total_rodadas, resultados, self.curva) = self._foto
        self.resultados = deque(resultados, maxlen=self.LIMITE_FEED)
        desfazer_registro_pesquisa(self)
        self._foto = None
        return True


def executar_backtest_bacbo(rodadas: int, semente: Optional[int], config: Optional[ConfigBacBo] = None,
                            padroes: Optional[List[PadraoBacBo]] = None, ao_progredir=None,
                            regra: str = REGRA_PADRAO) -> MotorBacBo:
    """Backtest do Bac Bo com dados simulados (mesma semente = mesmas rodadas)."""
    simulador = SimuladorBacBo(semente)
    motor = MotorBacBo(config or ConfigBacBo(), padroes, registrar=False, regra=regra)
    passo = max(1, rodadas // 100)
    curva = [(0, 0.0, 0.0)]
    for n in range(1, rodadas + 1):
        motor.processar(simulador.proxima())
        if n % passo == 0 or n == rodadas:
            curva.append((n, motor.banca.geral.lucro, motor.banca.esperado()))
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
    exibir(f"Entradas (1 por rodada) : {formatar_inteiro(total.sinais)}  (✅ {formatar_inteiro(total.greens)}"
           f" | salvos no empate {formatar_inteiro(total.greens_protecao)} | ❌ {formatar_inteiro(total.losses)})")
    exibir(f"Sem entrada (discordaram): {formatar_inteiro(motor.puladas)} rodadas"
           f"  (regra: {NOMES_REGRA[motor.regra].lower()})")
    exibir(f"Banca inicial → final   : {formatar_reais(banca.config.banca_inicial)} → {formatar_reais(banca.saldo)}")
    exibir(f"Total apostado          : {formatar_reais(total.apostado)}")
    exibir(f"Resultado real          : {formatar_reais(total.lucro, com_sinal=True)}")
    exibir(f"Esperado pela matemática: {formatar_reais(banca.esperado(), com_sinal=True)}"
           f"  (1,13% em Player/Banker e 4,48% no empate)")
    exibir("-" * 72)
    exibir("   Cada padrão como se entrasse sozinho:")
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
SEM_SOMA = "Não sei"


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


# -----------------------------------------------------------------------------------
# Banca -> valor das entradas (o painel calcula sozinho)
# -----------------------------------------------------------------------------------
# Regra fixa e conservadora: 1% da banca em cada alvo, arredondado para cima em reais, e
# a proteção (empate no Bac Bo, zero na roleta) com 10% da entrada. O valor NÃO aumenta
# depois de uma perda. No Bac Bo, a entrada nunca fica abaixo de R$ 5 (mínimo da mesa).
PCT_POR_ALVO = 0.01
PCT_PROTECAO = 0.10
MINIMO_MESA_BACBO = 5.0


def config_pela_banca(banca: float, bacbo: bool):
    entrada = max(MINIMO_MESA_BACBO if bacbo else 1.0, float(math.ceil(banca * PCT_POR_ALVO - 1e-9)))
    protecao = max(1.0, float(round(entrada * PCT_PROTECAO)))
    if bacbo:
        return ConfigBacBo(valor_por_alvo=entrada, protecao_empate=True, valor_protecao_empate=protecao, banca_inicial=banca)
    return Config(valor_por_alvo=entrada, protecao_zero=True, valor_protecao_zero=protecao, banca_inicial=banca)


def _banca_salva(jogo: str) -> float:
    try:
        valor = float(ler_config_painel().get(f"banca_{jogo}", 1000.0))
    except (TypeError, ValueError):
        valor = 1000.0
    return valor if valor >= 10 else 1000.0


def _config_salva(jogo: str):
    """Banca, entrada e proteção que você deixou salvas (sem entrada salva, usa 1% da banca)."""
    bacbo = jogo == "bacbo"
    config = config_pela_banca(_banca_salva(jogo), bacbo)
    salvo = ler_config_painel()
    try:
        entrada = float(salvo[f"entrada_{jogo}"])
        protecao = float(salvo[f"protecao_{jogo}"])
    except (KeyError, TypeError, ValueError):
        return config
    if entrada < 1 or protecao < 0:
        return config
    return _montar_config(config.banca_inicial, entrada, protecao, bacbo)


def _montar_config(banca: float, entrada: float, protecao: float, bacbo: bool):
    if bacbo:
        return ConfigBacBo(valor_por_alvo=entrada, protecao_empate=protecao > 0,
                           valor_protecao_empate=protecao, banca_inicial=banca)
    return Config(valor_por_alvo=entrada, protecao_zero=protecao > 0, valor_protecao_zero=protecao, banca_inicial=banca)


def _banca_lateral(st, alvo, bacbo: bool):
    """Banca, valor da entrada e da proteção + botão Entrar. Devolve a configuração da tela."""
    jogo = "bacbo" if bacbo else "roleta"
    atual = alvo.config
    protecao_atual = atual.valor_protecao_empate if bacbo else atual.valor_protecao_zero
    st.markdown('<div class="rr-sub" style="margin-top:10px">Sua banca</div>', unsafe_allow_html=True)
    banca = st.number_input("Valor da banca (R$)", min_value=10.0, max_value=10_000_000.0,
                            value=float(atual.banca_inicial), step=10.0, key=f"rr_banca_{jogo}")
    entrada = st.number_input("Valor da entrada (R$)" if bacbo else "Valor da entrada, em cada alvo (R$)",
                              min_value=1.0, max_value=100_000.0, value=float(atual.valor_por_alvo), step=1.0,
                              key=f"rr_entrada_{jogo}")
    protecao = st.number_input("Valor no empate (R$)" if bacbo else "Valor no zero (R$)", min_value=0.0,
                               max_value=100_000.0, value=float(protecao_atual), step=0.5, key=f"rr_protecao_{jogo}")
    sugestao = config_pela_banca(float(banca), bacbo)
    sug_protecao = sugestao.valor_protecao_empate if bacbo else sugestao.valor_protecao_zero
    st.caption(f"Sugestão para essa banca (1% por alvo): {formatar_reais(sugestao.valor_por_alvo)} + "
               f"{formatar_reais(sug_protecao)} {'no empate' if bacbo else 'no zero'}. Valor 0 = sem proteção.")
    config = _montar_config(float(banca), float(entrada), float(protecao), bacbo)
    campos = ("valor_por_alvo", "banca_inicial") + (("valor_protecao_empate",) if bacbo else ("valor_protecao_zero",))
    mudou = any(getattr(atual, c) != getattr(config, c) for c in campos)
    if st.button("Entrar", key="rr_entrar", type="primary" if mudou else "secondary"):
        alvo.nova_sessao(config)
        salvar_config_painel({f"banca_{jogo}": float(banca), f"entrada_{jogo}": float(entrada),
                              f"protecao_{jogo}": float(protecao)})
        mudou = False
    if mudou:
        st.caption("Clique em Entrar para começar com esses valores.")
    return config


# -----------------------------------------------------------------------------------
# Botão "Salvar sessão": baixa uma planilha (CSV, abre no Excel) com cada entrada
# -----------------------------------------------------------------------------------
def _planilha(linhas: List[List[str]]) -> bytes:
    saida = io.StringIO()
    csv.writer(saida, delimiter=";", lineterminator="\r\n").writerows(linhas)
    return saida.getvalue().encode("utf-8-sig")  # com BOM: o Excel reconhece os acentos


def _reais_planilha(valor: float) -> str:
    return f"{valor:.2f}".replace(".", ",")


def _bancas_depois(saldo: float, lucros: List[float]) -> List[float]:
    """Banca depois de cada entrada, calculada de trás para a frente a partir da banca atual."""
    depois, atual = [], saldo
    for lucro in reversed(lucros):
        depois.append(atual)
        atual -= lucro
    return list(reversed(depois))


def csv_sessao_bacbo(motor: MotorBacBo) -> bytes:
    itens = list(motor.resultados)
    linhas = [["Data e hora", "Saiu", "Soma", "Padrão", "Entrada em", "Resultado",
               "Apostado (R$)", "Lucro (R$)", "Banca depois (R$)"]]
    for r, banca in zip(itens, _bancas_depois(motor.banca.saldo, [r.lucro for r in itens])):
        linhas.append([r.rodada.horario.strftime("%d/%m/%Y %H:%M:%S"), NOMES_LADO[r.rodada.resultado],
                       str(r.rodada.soma_vencedora or ""), r.sinal.nome, NOMES_LADO[r.sinal.alvo], r.status,
                       _reais_planilha(r.total_apostado), _reais_planilha(r.lucro), _reais_planilha(banca)])
    return _planilha(linhas)


def csv_sessao_roleta(motor: MotorWeb) -> bytes:
    itens = list(motor.resultados)
    linhas = [["Data e hora", "Número", "Padrão", "Entrada em", "Resultado",
               "Apostado (R$)", "Lucro (R$)", "Banca depois (R$)"]]
    for r, banca in zip(itens, _bancas_depois(motor.banca.saldo, [r.lucro for r in itens])):
        if r.sinal.tipo == "cor":
            alvo = str(r.sinal.alvos[0])
        else:
            alvo = ("dúzias " if r.sinal.tipo == "duzia" else "colunas ") + " e ".join(str(a) for a in r.sinal.alvos)
        linhas.append([r.giro.horario.strftime("%d/%m/%Y %H:%M:%S"), str(r.giro.numero), r.sinal.padrao, alvo,
                       r.status, _reais_planilha(r.total_apostado), _reais_planilha(r.lucro), _reais_planilha(banca)])
    return _planilha(linhas)


def _botao_salvar(st, dados: bytes, jogo: str, prefixo: str) -> None:
    _, coluna = st.columns([4, 1])
    coluna.download_button("Salvar sessão", data=dados, mime="text/csv", key=f"{prefixo}_salvar",
                           file_name=f"sessao_{jogo}_{datetime.now():%Y-%m-%d_%H-%M}.csv")


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
        regra = salvo.get("bacbo_regra")
        self.regra: str = regra if regra in NOMES_REGRA else REGRA_PADRAO
        self.config = _config_salva("bacbo") if no_meu_pc else ConfigBacBo()
        self.motor = MotorBacBo(self.config, self.padroes, regra=self.regra)
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

    def atualizar_padroes(self, desligados: List[str], extras_txt: str, regra: Optional[str] = None) -> None:
        regra = regra if regra in NOMES_REGRA else self.regra
        with self.trava:
            if desligados == self.desligados and extras_txt == self.extras_txt and regra == self.regra:
                return
            self.desligados, self.extras_txt, self.regra = list(desligados), extras_txt, regra
            self.padroes = self._montar_padroes()
            # Vale na hora: o alerta da tela passa a mostrar só o que os padrões novos enxergam
            self.motor.estrategia.padroes = list(self.padroes)
            self.motor.regra = regra
            self.motor.reanalisar()
            if self.no_meu_pc:
                salvar_config_painel({"bacbo_padroes_desligados": self.desligados,
                                      "bacbo_padroes_extras": self.extras_txt, "bacbo_regra": self.regra})

    def padroes_sao_os_prontos(self) -> bool:
        return [p.chave for p in self.padroes] == [p.chave for p in PADROES_BACBO] and self.regra == REGRA_PADRAO

    # --- sessão --------------------------------------------------------------------
    def nova_sessao(self, config: ConfigBacBo) -> None:
        with self.trava:
            rodadas = list(self.motor.historico)
            self.config = config
            self.motor = MotorBacBo(config, self.padroes, regra=self.regra)
            if rodadas:
                _carregar_historico_bacbo(self.motor, rodadas)

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
    motor.reanalisar()
    sincronizar_historico_pesquisa(motor)


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
            teorico = sum(n * MATEMATICA_BACBO[tipo]["chance_teorica"] for tipo, n in banca.entradas_tipo.items()) / total.sinais
            acerto_txt, acerto_det = formatar_pct(total.taxa_acerto), f"chance real dos alvos: {formatar_pct(teorico)}"
        else:
            acerto_txt, acerto_det = "—", "aparece depois do primeiro sinal"
        esperado = banca.esperado()
        return '<div class="rr-cartoes">' + "".join([
            Html.cartao("Banca", formatar_reais(banca.saldo),
                        f'<span class="{"rr-pos" if variacao >= 0 else "rr-neg"}">{formatar_reais(variacao, com_sinal=True)}</span>'
                        f" desde o início"),
            Html.cartao("Acerto geral", acerto_txt, acerto_det),
            Html.cartao("Entradas conferidas", formatar_inteiro(total.sinais),
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
                f'</div><div class="rr-validade">Vale só para a próxima rodada. O painel confere sozinho e lança na banca.</div></div>')

    @staticmethod
    def _lista_sinais(sinais: List[SinalBacBo]) -> str:
        return " · ".join(f"{html.escape(s.nome)} ({NOMES_LADO[s.alvo]})" for s in sinais)

    @classmethod
    def alertas(cls, motor: MotorBacBo) -> str:
        aviso = (f'<div class="rr-aviso">Ficou de fora por discordar do padrão mais longo: '
                 f'{cls._lista_sinais(motor.descartados)}</div>') if motor.descartados else ""
        return "".join(cls.alerta(s, motor) for s in motor.pendentes) + aviso

    @classmethod
    def sem_alerta(cls, motor: MotorBacBo, padroes: List[PadraoBacBo]) -> str:
        ultimo = cls.chip(motor.historico[-1], "pq") if motor.historico else ""
        if motor.descartados:  # os padrões discordaram e a regra mandou não entrar
            return (f'<div class="rr-calmo">{ultimo}<div><b>Padrões discordaram: sem entrada nesta rodada</b><br>'
                    f'<span>{cls._lista_sinais(motor.descartados)}</span></div></div>')
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
                f'<div class="rr-nota">Cada padrão aparece como se entrasse sozinho, para dar para comparar; a banca conta uma entrada '
                f'por rodada. Acerto é quantas vezes o alvo saiu. Em Player ou Banker, o empate dos dados não conta como acerto '
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
    if "bb_regra" not in st.session_state:
        st.session_state["bb_regra"] = NOMES_REGRA[bacbo.regra]
    with st.expander("Padrões do Bac Bo"):
        escolhidos = st.multiselect("Padrões prontos ligados", list(nomes.values()), key="bb_pad_sel")
        texto = st.text_area("Seus padrões (um por linha)", key="bb_pad_extra", height=120,
                             placeholder="PPB -> P\nBBBB -> P\nEP -> E")
        nome_regra = st.radio("Se os padrões discordarem na mesma rodada", list(NOMES_REGRA.values()), key="bb_regra",
                              help="O robô dá uma entrada só por rodada. Padrões que apontam o mesmo alvo viram "
                                   "uma entrada; se apontarem alvos diferentes, vale esta regra.")
        regra = next(chave for chave, nome in NOMES_REGRA.items() if nome == nome_regra)
        bacbo.atualizar_padroes([ch for ch, nome in nomes.items() if nome not in escolhidos], texto or "", regra)
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


def app_bacbo(st, bacbo: SessaoBacBo, modo: str, no_meu_pc: bool, config_tela: ConfigBacBo,
              som: Optional[dict] = None) -> None:
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
        _resumo_monitor_pesquisa(st, motor, "bacbo")
        if motor.pendentes:
            st.markdown(HtmlBacBo.alertas(motor), unsafe_allow_html=True)
        else:
            st.markdown(HtmlBacBo.sem_alerta(motor, bacbo.padroes), unsafe_allow_html=True)
        st.markdown(HtmlBacBo.feed(motor, limite=12), unsafe_allow_html=True)
        _botao_salvar(st, csv_sessao_bacbo(motor), "bacbo", "bb")
        st.markdown(Html.grafico_curva(motor.curva, "Banca da sessão", "rodadas", HtmlBacBo.PREVISTO),
                    unsafe_allow_html=True)
        _tocar_sons(st, _eventos_som_bacbo(motor, som))

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
                                            ao_progredir=lambda f: barra.progress(min(1.0, f), text=f"Simulando... {f * 100:.0f}%"),
                                            regra=bacbo.regra)
            barra.empty()
            bacbo.backtest = {"rodadas": int(rodadas), "semente": int(semente), "motor": motor,
                              "padroes": list(bacbo.padroes), "segundos": time.time() - inicio,
                              "padrao": config_tela == ConfigBacBo() and bacbo.padroes_sao_os_prontos()}

    resultado = bacbo.backtest
    if not resultado and demonstracao is not None:
        resultado = demonstracao()  # versão hospedada: mostra o teste de aceitação já pronto
    if not resultado:
        st.markdown('<div class="rr-calmo"><div><b>Rode um backtest</b><br><span>1.000.000 de rodadas com semente 42, '
                    'os 6 padrões prontos, os ajustes padrão e “vale o padrão mais longo” é o teste de aceitação: '
                    'tem que dar 515.257 entradas e −R$ 105.951,00.</span></div></div>', unsafe_allow_html=True)
        return
    if resultado.get("demonstracao"):
        st.caption("Demonstração com os 6 padrões prontos, os ajustes padrão e “vale o padrão mais longo”. "
                   "Rode o seu backtest para testar os padrões e a regra que você escolheu.")
    motor: MotorBacBo = resultado["motor"]
    total = motor.banca.total()
    st.markdown('<div class="rr-cartoes">' + "".join([
        Html.cartao("Rodadas simuladas", formatar_inteiro(resultado["rodadas"]),
                    f'semente {resultado["semente"]} · {resultado["segundos"]:.1f} s'),
        Html.cartao("Entradas conferidas", formatar_inteiro(total.sinais),
                    f'<span class="rr-pos">{formatar_inteiro(total.greens)} GREEN</span> · '
                    f'<span class="rr-neg">{formatar_inteiro(total.losses)} LOSS</span> · '
                    f'{formatar_inteiro(motor.puladas)} sem entrada (discordaram)'),
        Html.cartao("Resultado real", formatar_reais(total.lucro, com_sinal=True),
                    (f"{total.lucro / total.apostado * 100:.2f}%".replace(".", ",") + " do total apostado")
                    if total.apostado else "nenhum sinal disparado",
                    "rr-pos" if total.lucro > 0 else "rr-neg"),
        Html.cartao("Esperado pela matemática", formatar_reais(motor.banca.esperado(), com_sinal=True),
                    "1,13% em Player/Banker · 4,48% no empate"),
    ]) + "</div>", unsafe_allow_html=True)
    if resultado["rodadas"] == 1_000_000 and resultado["semente"] == 42 and resultado["padrao"]:
        bateu = total.sinais == 515_257 and round(total.lucro, 2) == -105_951.0
        st.markdown(f'<div class="rr-selo {"ok" if bateu else "nao"}">'
                    f'{"Teste de aceitação: bateu" if bateu else "Teste de aceitação: NÃO bateu"} · '
                    f'{formatar_inteiro(total.sinais)} entradas · {formatar_reais(total.lucro, com_sinal=True)}</div>',
                    unsafe_allow_html=True)
    st.markdown(Html.grafico_curva(motor.curva, "Banca no backtest", "rodadas", HtmlBacBo.PREVISTO), unsafe_allow_html=True)
    st.markdown(HtmlBacBo.tabela(motor.banca, resultado["padroes"], "Desempenho por padrão no backtest"),
                unsafe_allow_html=True)


# ===================================================================================
# 13) LOBBY 3D E SOM DOS SINAIS
# -----------------------------------------------------------------------------------
# Lobby: a primeira tela do painel, para escolher a mesa. Tudo em CSS 3D (roleta girando
# e dados rolando), sem bibliotecas e sem JavaScript, então funciona no Markdown do Streamlit.
# Som: um componente HTML invisível que toca com a Web Audio API do navegador (nenhum
# arquivo de áudio). Cada som tem uma identidade guardada no navegador, para nunca tocar
# duas vezes o mesmo sinal, mesmo que a tela seja redesenhada.
# ===================================================================================
RODA_EUROPEIA = [0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8, 23, 10, 5,
                 24, 16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28, 12, 35, 3, 26]
PONTOS_DADO = {1: [(50, 50)], 2: [(28, 28), (72, 72)], 3: [(26, 26), (50, 50), (74, 74)],
               4: [(28, 28), (72, 28), (28, 72), (72, 72)],
               5: [(28, 28), (72, 28), (50, 50), (28, 72), (72, 72)],
               6: [(28, 24), (72, 24), (28, 50), (72, 50), (28, 76), (72, 76)]}
FACES_DADO = {"f1": (1, "translateZ(37px)"), "f2": (3, "rotateY(90deg) translateZ(37px)"),
              "f3": (6, "rotateY(180deg) translateZ(37px)"), "f4": (4, "rotateY(-90deg) translateZ(37px)"),
              "f5": (2, "rotateX(90deg) translateZ(37px)"), "f6": (5, "rotateX(-90deg) translateZ(37px)")}


def _css_visual_realista() -> str:
    """Tema visual autocontido: sem fontes, imagens ou CDNs externas."""
    return r"""
:root{
 --rr-bg:#080e0c;--rr-surface:#111b17;--rr-surface2:#19261f;--rr-line:#2a3930;
 --rr-ink:#f0ede4;--rr-ink2:#adb7ad;--rr-muted:#91a193;--rr-red:#c75b65;
 --rr-black:#141918;--rr-green:#6ac69b;--rr-blue:#7da4d4;--rr-gold:#cfb37c;
 --rr-good:#7cceaa;--rr-bad:#e58b8b;
 --rr-display:'Segoe UI',Arial,system-ui,sans-serif;
 --rr-mono:'Cascadia Code','SFMono-Regular',Consolas,monospace;
 --lb-brass:#cfb37c;--lb-brass-light:#f0dbac;--lb-cream:#f3eee2;
}
.stApp,[data-testid='stAppViewContainer']{
 background:radial-gradient(ellipse at 54% 0%,rgba(117,109,69,.12),transparent 52%),
 radial-gradient(ellipse at 100% 62%,rgba(38,79,56,.10),transparent 58%),#080e0c!important;
 color:var(--rr-ink);font-family:var(--rr-display);
}
[data-testid='stHeader']{background:transparent!important;}
.stApp [data-testid='stSidebar']{background:linear-gradient(180deg,#111c16,#0b130f 70%)!important;border-right:1px solid #28372a;}
.stApp [data-testid='stSidebarContent']{padding-top:1rem;}
.stApp .block-container{padding-top:2rem;padding-bottom:2.5rem;max-width:1320px;}
.stApp [data-testid='stSidebar'] p,.stApp [data-testid='stSidebar'] label{font-size:.88rem;}
.stApp p,.stApp label{line-height:1.6;}
.stApp [data-testid='stCaptionContainer'] *,.stApp small{color:var(--rr-muted)!important;}
.stApp [data-baseweb='input'],.stApp [data-baseweb='select']>div,.stApp [data-baseweb='base-input'],
.stApp textarea,.stApp input{background:#142019!important;color:#eeeade!important;border-color:#354336!important;}
.stApp [role='radiogroup'] label{padding-block:4px;}
.stApp [data-testid='stMetric']{background:linear-gradient(145deg,#19251c,#101a14);border:1px solid #344132;border-radius:13px;padding:14px 16px;}
.stApp [data-testid='stMetricValue']{font-family:var(--rr-display);font-weight:600;color:var(--rr-ink);}
.stApp [data-testid='stMetricLabel']{color:var(--rr-muted);}
.stApp .stButton>button,.stApp .stDownloadButton>button{
 border:1px solid #394535;background:linear-gradient(180deg,#223025,#17221a);
 color:#e4e4d8;border-radius:9px;font-family:var(--rr-display);font-weight:600;min-height:42px;
 box-shadow:inset 0 1px 0 #ffffff08,0 3px 8px #00000028;transition:background .2s,border-color .2s,transform .2s;
}
.stApp .stButton>button:hover,.stApp .stDownloadButton>button:hover{border-color:#b49c64;color:#fff3d3;background:#273427;}
.stApp .stButton>button[kind='primary']{
 background:linear-gradient(145deg,#e1c995,#bca068)!important;border-color:#ddc28c!important;
 color:#1b2119!important;box-shadow:inset 0 1px 0 #fff8,0 5px 18px #0005;
}
.stApp .stButton>button[kind='primary'] p{color:#1b2119!important;}
.stApp button:focus-visible,.stApp input:focus-visible{outline:2px solid #e3c789!important;outline-offset:4px;}
.stApp [data-testid='stExpander']{border:1px solid #2e3c30;background:#101b15;border-radius:13px;box-shadow:none;}
.stApp [data-testid='stExpander'] details summary{padding-block:12px;background:#18251b;border-radius:12px;}
.stApp [data-testid='stDataFrame']{border:1px solid #3c4938;border-radius:11px;overflow:hidden;}
.stApp [data-testid='stFileUploader']{border-radius:12px;}
.stApp [data-testid='stProgress'] div[role='progressbar']>div>div{background:var(--rr-gold)!important;}
.rr-marca{font-size:1.15rem;font-weight:650;letter-spacing:-.025em;color:#efe8d6;gap:10px;}
.rr-marca i,.rr-marca.lb i,.rr-marca.bb i{
 width:23px;height:23px;border:2px solid #b29a65;box-shadow:inset 0 0 0 3px #111d15,0 0 0 1px #493e28;
 background:conic-gradient(#9d3441 0 20%,#1c241d 20% 42%,#397651 42% 48%,#1c241d 48% 70%,#9d3441 70% 90%,#1c241d 90%);
}
.rr-sub{font-size:.66rem;letter-spacing:.14em;color:#a8b2a0;font-weight:500;line-height:1.6;}
.rr-topo{margin-bottom:24px;gap:14px;}
.rr-titulo{font-size:clamp(1.8rem,3vw,2.5rem);font-weight:600;letter-spacing:-.045em;line-height:1.15;text-shadow:none;color:#f3eee2;}
.rr-status{padding:8px 12px;border-color:#354234;background:#142019;color:#c5d0bc;font-size:.7rem;}
.rr-status.on i{background:#78c19d;box-shadow:0 0 0 4px #78c19d12;animation:none;}
.rr-cartoes{gap:12px;margin:6px 0 24px;}
.rr-cartao{position:relative;background:linear-gradient(135deg,#1a281e,#111c15);border:1px solid #354333;border-radius:13px;padding:20px 18px;gap:10px;box-shadow:inset 0 1px 0 #ffffff05,0 7px 18px #00000020;transition:border-color .2s;}
.rr-cartao:hover{transform:none;border-color:#8b7d51;box-shadow:inset 0 1px 0 #ffffff05,0 7px 18px #00000020;}
.rr-cartao:before{content:'';position:absolute;left:18px;top:0;width:28px;height:2px;background:#b99d62;opacity:.8;}
.rr-cartao .r{font-size:.64rem;color:#9eaf98;letter-spacing:.09em;}
.rr-cartao .v{font-size:clamp(1.15rem,1.7vw,1.6rem)!important;font-weight:550;letter-spacing:-.035em;line-height:1.2;white-space:normal;overflow:visible;text-overflow:clip;overflow-wrap:anywhere;}
.rr-cartao .d{font-size:.7rem;color:#a0b29f;line-height:1.5;}
.rr-bloco{background:linear-gradient(145deg,#142019,#101a14);border:1px solid #2d3c2e;border-radius:13px;box-shadow:inset 0 1px 0 #ffffff04;margin-bottom:20px;padding:20px;}
.rr-bloco .rr-h{font-weight:600;font-size:1rem;letter-spacing:-.01em;}
.rr-bloco .rr-h small{font-size:.61rem;}
.rr-calmo{background:#131e17;border:1px dashed #40503b;border-radius:13px;padding:20px;}
.rr-calmo b{font-weight:600;}.rr-calmo span{font-size:.74rem;line-height:1.6;}
.rr-alerta,.bb-alerta{background:linear-gradient(125deg,#2b2619,#182219 70%);border-color:#9c834f;box-shadow:0 5px 18px #0004;animation:none;border-radius:13px;}
.rr-alerta .tag{color:#d8bd80;}.rr-alerta .pad{font-weight:650;}
.rr-alvo{border-color:#5b5337;background:linear-gradient(145deg,#2e301f,#1d281c);border-radius:9px;font-weight:600;}
.rr-valor{font-weight:600;}.rr-validade{line-height:1.5;}
.rr-pedra,.bb-chip{border:1px solid #ffffff25;box-shadow:inset 0 1px 2px #ffffff16,0 3px 5px #0005!important;}
.rr-pedra.v{background:radial-gradient(circle at 35% 25%,#b44b56,#791f2c 80%);}
.rr-pedra.p{background:radial-gradient(circle at 35% 25%,#3f4941,#121a15 80%);}
.rr-pedra.z{background:radial-gradient(circle at 35% 25%,#659671,#22573b 80%);color:#fff;}
.rr-pedra.nova,.bb-chip.nova{animation:none;outline:1px solid #d0b77c;outline-offset:4px;}
.bb-chip.p{background:radial-gradient(circle at 35% 25%,#658bb6,#2d4c77 85%);}
.bb-chip.b{background:radial-gradient(circle at 35% 25%,#b1666b,#772f3a 85%);}
.bb-chip.e{background:radial-gradient(circle at 35% 25%,#e2c78e,#9e834d 85%);color:#1a2118;}
.rr-feed{gap:7px;}.rr-item{background:#1b291e;border:1px solid #2f3e2e;padding:10px 12px;}
.rr-item .t{font-size:.82rem;color:#bcc8b7;}.rr-badge{font-size:.64rem;font-weight:500;}
.rr-tabela th{font-size:.61rem;border-color:#33412e;color:#9bad92;}
.rr-tabela td{font-size:.76rem;border-color:#273726;padding:11px 6px;}
.rr-nota{color:#9aae92;font-size:.76rem;}.rr-graf text{fill:#99ac91;}
.rr-graf svg{overflow:visible;}.rr-legenda{font-size:.67rem;}
.rr-pos{color:#83cfaa!important;}.rr-neg{color:#e7a29a!important;}
.stApp [data-testid='stHorizontalBlock']:has([class*='st-key-rr_num_']){gap:5px!important;}
.stApp [data-testid='stHorizontalBlock']:has([class*='st-key-rr_num_']) button{border-radius:7px!important;box-shadow:inset 0 1px 0 #fff2,0 3px 5px #0004!important;min-width:0;padding:3px!important;}
@media(max-width:1050px){.rr-cartoes{grid-template-columns:repeat(2,minmax(0,1fr));}.rr-cartao .v{font-size:1.6rem;}}
@media(max-width:700px){
 .stApp .block-container{padding:1rem 1rem 2rem;}.rr-titulo{font-size:1.85rem;}.rr-topo{margin-bottom:20px;}
 .rr-cartoes{gap:9px;}.rr-cartao{padding:16px 12px;}.rr-cartao .v{font-size:1.4rem;white-space:normal;overflow-wrap:anywhere;}
 .rr-cartao .r{font-size:.58rem;}.rr-cartao .d{font-size:.63rem;}.rr-bloco{padding:15px 12px;overflow-x:auto;}
 .rr-alerta{padding:18px 15px;}.rr-alerta .grade{grid-template-columns:1fr;gap:14px;}
 .rr-tabela{min-width:480px;}.rr-item{gap:8px;padding:9px 8px;}.rr-item .t{font-size:.74rem;}
 .stApp [data-testid='stHorizontalBlock']:has([class*='st-key-rr_num_']){display:grid!important;grid-template-columns:repeat(6,minmax(0,1fr));gap:7px!important;}
 .stApp [data-testid='stHorizontalBlock']:has([class*='st-key-rr_num_'])>[data-testid='stColumn']{width:auto!important;min-width:0!important;}
 .stApp [data-testid='stHorizontalBlock']:has([class*='st-key-rr_num_'])>[data-testid='stColumn']:not(:has(button)){display:none;}
}
@media(prefers-reduced-motion:reduce){*,*:before,*:after{animation:none!important;scroll-behavior:auto!important;transition:none!important;}}
"""

def _css_lobby_e_som() -> str:
    """Materiais e geometria 3D gerados em CSS; dados e roleta são decorativos."""
    return r"""
.element-container:has(iframe[height='0']),[data-testid='stElementContainer']:has(iframe[height='0']){position:absolute!important;width:0!important;height:0!important;overflow:hidden!important;margin:0!important;}
.lb-topo{margin:0 0 28px;position:relative;}
.stApp [data-testid='stAppDeployButton']{display:none;}
.stApp h1.lb-titulo{font-family:Georgia,'Times New Roman',serif!important;font-weight:400!important;font-size:clamp(2.4rem,4.4vw,4rem)!important;letter-spacing:-.045em!important;line-height:1.08!important;}
.stApp [data-testid='stHorizontalBlock']:has(.lb-card){display:grid!important;grid-template-columns:repeat(2,minmax(0,1fr));gap:24px!important;}
.stApp [data-testid='stHorizontalBlock']:has(.lb-card)>[data-testid='stColumn']{width:100%!important;min-width:0!important;}
@media(max-width:1150px){.stApp [data-testid='stHorizontalBlock']:has(.lb-card){grid-template-columns:1fr;}}
@media(max-width:700px){.stApp h1.lb-titulo{font-size:2.7rem!important;}}
@media(max-width:380px){.stApp h1.lb-titulo{font-size:2.3rem!important;}}
.lb-barra{display:flex;align-items:center;justify-content:space-between;gap:20px;padding-bottom:22px;border-bottom:1px solid #9f956222;}
.lb-assinatura{display:flex;align-items:center;gap:10px;font-size:.72rem;letter-spacing:.18em;color:#e4d6b4;font-weight:500;}
.lb-assinatura svg{width:25px;height:25px;flex:none;}
.lb-edicao{font-family:var(--rr-mono);font-size:.58rem;letter-spacing:.13em;color:#a1ac93;}
.lb-hero{display:flex;justify-content:space-between;gap:28px;align-items:flex-end;margin:28px 0 32px;}
.lb-kicker{font-size:.59rem;letter-spacing:.23em;text-transform:uppercase;color:#d5b97a;font-family:var(--rr-mono);margin-bottom:12px;}
.lb-titulo{font-family:Georgia,'Times New Roman',serif;font-size:clamp(2.4rem,4.4vw,4rem);font-weight:400;letter-spacing:-.045em;line-height:1.08;color:#f2ebdb;margin:0;text-shadow:0 4px 18px #0004;}
.lb-titulo em{font-weight:400;font-style:italic;color:#d1b781;}
.lb-sub{font-family:var(--rr-display);font-size:.9rem;line-height:1.75;color:#b0bba8;max-width:310px;margin:0 0 4px;}
.lb-divisor{display:flex;align-items:center;gap:14px;font-family:var(--rr-mono);font-size:.58rem;letter-spacing:.17em;color:#adba9c;}
.lb-divisor:after{content:'';height:1px;background:linear-gradient(90deg,#c5b27932,transparent);flex:1;}
.lb-card{position:relative;border-radius:17px;padding:0;overflow:hidden;margin-bottom:0;border:1px solid #4c4b32;
 background:linear-gradient(155deg,#1d281b,#101b13 85%);box-shadow:0 10px 32px #0003,inset 0 1px 0 #ffffff05;transition:border-color .25s,box-shadow .25s;}
.lb-card:hover{border-color:#a68f57;box-shadow:0 12px 35px #0005,inset 0 1px 0 #ffffff08;}
.lb-card:after{content:'';position:absolute;inset:0;border-radius:inherit;border:1px solid #d2c69a05;pointer-events:none;}
.lb-card-top{position:absolute;z-index:9;inset:17px 19px auto;display:flex;align-items:center;justify-content:space-between;gap:12px;}
.lb-card-index{font-family:var(--rr-mono);font-size:.55rem;color:#aeba9e;letter-spacing:.17em;}
.lb-card-format{font-family:var(--rr-mono);font-size:.53rem;letter-spacing:.1em;color:#cfc090;border:1px solid #b1a5752b;background:#0a140d77;padding:5px 8px;border-radius:4px;}
.lb-cena{height:300px;position:relative;isolation:isolate;overflow:hidden;display:flex;align-items:center;justify-content:center;
 background:radial-gradient(ellipse at 48% 36%,#43533b 0%,#243c29 35%,#132a1b 70%,#102016 100%);border-bottom:1px solid #8e895529;}
.lb-cena:before{content:'';position:absolute;inset:0;background:repeating-linear-gradient(0deg,#afc99b04 0px,#afc99b04 1px,transparent 1px,transparent 3px),repeating-linear-gradient(90deg,#00000005 0px,#00000005 1px,transparent 1px,transparent 3px);mix-blend-mode:screen;pointer-events:none;}
.lb-cena:after{content:'';position:absolute;inset:0;background:radial-gradient(ellipse at 40% 12%,#f9dca621,transparent 62%),linear-gradient(0deg,#08120d5c,transparent 30%);pointer-events:none;z-index:8;}
.lb-stage-code{position:absolute;bottom:14px;left:19px;z-index:9;color:#a4b8958c;font-family:var(--rr-mono);font-size:.48rem;letter-spacing:.18em;}
.lb-stage-mark{position:absolute;right:19px;bottom:13px;font-family:Georgia,serif;font-style:italic;font-size:.85rem;letter-spacing:.02em;color:#bec5a23d;z-index:9;}
.lb-info{padding:22px 22px 20px;position:relative;z-index:9;background:linear-gradient(135deg,#1b271b,#111c13);}
.lb-info-top{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:8px;}
.lb-nome{font-family:Georgia,'Times New Roman',serif;font-weight:400;font-size:1.8rem;line-height:1.15;letter-spacing:-.035em;color:#f1e9d9;}
.lb-arrow{font-family:var(--rr-display);font-size:1.4rem;color:#cfb477;opacity:.8;}
.lb-desc{font-size:.77rem;line-height:1.6;color:#afbea4;min-height:25px;}
.lb-linha{display:flex;gap:7px;flex-wrap:wrap;margin-top:17px;padding-top:16px;border-top:1px solid #9d9c6320;}
.lb-pill{display:inline-flex;gap:6px;align-items:center;font-family:var(--rr-mono);font-size:.67rem;line-height:1.3;padding:5px 7px;border-radius:4px;background:#ffffff03;border:1px solid #7b8e6126;color:#a6b699;}
.lb-pill i{width:5px;height:5px;display:inline-block;border-radius:50%;background:#89977d;flex:none;}
.lb-pill.on{color:#b5deba;border-color:#73ba8d55;background:#80c19909;}.lb-pill.on i{background:#8dd5a4;box-shadow:0 0 5px #89d2a844;}
.lb-rodape{margin-top:24px;padding-top:18px;border-top:1px solid #83965d22;display:flex;justify-content:space-between;align-items:center;gap:24px;font-size:.68rem;line-height:1.6;color:#98a68b;}
.lb-rodape b{font-family:var(--rr-mono);font-weight:400;font-size:.57rem;letter-spacing:.14em;color:#b7b48d;white-space:nowrap;}
.st-key-lb_roleta button,.st-key-lb_bacbo button{width:100%;min-height:48px!important;border-radius:9px!important;border:1px solid #dac18b!important;background:linear-gradient(120deg,#ddc58f,#bda16b)!important;box-shadow:inset 0 1px 0 #fff6,0 5px 12px #0003!important;}
.st-key-lb_roleta button p,.st-key-lb_bacbo button p{color:#172015!important;font-size:.85rem!important;font-weight:650!important;letter-spacing:.02em;}
.st-key-lb_roleta button:hover,.st-key-lb_bacbo button:hover{background:linear-gradient(120deg,#ecdbaf,#c7af7b)!important;transform:translateY(-1px);}
.st-key-lb_roleta button:active,.st-key-lb_bacbo button:active{transform:translateY(1px);}
/* A moldura permanece fixa: somente o prato e a esfera giram. */
.lb-wheel-wrap{position:relative;width:min(88%,365px);aspect-ratio:1;perspective:900px;transform:translateY(3px);z-index:2;flex:none;}
.lb-wheel-shadow{position:absolute;inset:29% 3% 4%;border-radius:50%;background:#020804;filter:blur(12px);opacity:.75;transform:translateY(21px);}
.lb-wheel-base{position:absolute;inset:0;border-radius:50%;background:linear-gradient(145deg,#8b5930,#392112 45%,#160f09 100%);transform:rotateX(43deg) rotateZ(-12deg) translateZ(-17px);box-shadow:0 18px 0 #2a190e,0 22px 0 #14110a;}
.lb-wheel{position:absolute;inset:0;transform-style:preserve-3d;transform:rotateX(43deg) rotateZ(-12deg);}
.lb-wheel>svg{position:absolute;inset:0;width:100%;height:100%;overflow:visible;}
.lb-wheel .lb-rotor{animation:lb-wheel-turn 38s linear infinite;transform-origin:50% 50%;}
.lb-wheel .lb-ball-orbit{animation:lb-ball-turn 13s linear infinite;transform-origin:50% 50%;}
.lb-wheel .lb-gloss{pointer-events:none;}
@keyframes lb-wheel-turn{from{transform:rotate(0deg)}to{transform:rotate(360deg)}}
@keyframes lb-ball-turn{from{transform:rotate(45deg)}to{transform:rotate(-315deg)}}
/* Fichas em cerâmica, vistas em perspectiva sobre o feltro. */
.lb-chip-stack{position:absolute;left:25px;bottom:39px;width:44px;height:44px;z-index:7;transform:rotateX(43deg) rotateZ(-18deg);border-radius:50%;
 background:radial-gradient(circle,#344132 0 40%,#d4c49b 41% 43%,#283d29 44% 62%,transparent 63%),repeating-conic-gradient(#d5c6a0 0 11deg,#315537 11deg 55deg,#d5c6a0 55deg 66deg,#315537 66deg 120deg);
 box-shadow:0 3px 0 #b6aa87,0 5px 0 #243c27,0 7px 0 #c6b68e,0 9px 0 #27462d,0 12px 10px #0008;border:1px solid #d4c8a2;}
.lb-chip-stack:after{content:'10';position:absolute;inset:0;display:grid;place-items:center;font-family:Georgia,serif;font-size:.75rem;color:#d1c59e;}
/* Quatro cúpulas de vidro, duas para cada lado, com bases de latão. */
.lb-bacbo .lb-cena{background:radial-gradient(ellipse at 48% 36%,#3f503d,#203c2b 38%,#10271d 78%);}
.lb-felt-oval{position:absolute;width:78%;height:65%;left:11%;top:23%;border:1px solid #b7b58a26;border-radius:50%;transform:rotateX(33deg);box-shadow:0 0 0 7px #0f221a44,0 0 0 8px #b7b58a16;}
.lb-shakers{position:relative;display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;width:90%;max-width:390px;align-items:end;z-index:3;margin-top:-4px;}
.lb-shaker{position:relative;height:146px;perspective:550px;--die:46px;--half:23px;}
.lb-shaker:after{content:'';position:absolute;bottom:2px;left:0;right:0;height:20px;background:#020703;filter:blur(6px);border-radius:50%;z-index:0;}
.lb-shaker-base{position:absolute;bottom:8px;left:0;right:0;height:25px;border-radius:50%;z-index:2;
 background:linear-gradient(105deg,#756039 0%,#eddaa3 18%,#b79a5b 34%,#6a552c 55%,#dfcb96 77%,#756039 100%);border:1px solid #b49d6b;box-shadow:inset 0 -5px 3px #30270e,0 4px 0 #2a2614;}
.lb-shaker-base:after{content:'';position:absolute;inset:2px 3px 7px;border-radius:50%;background:radial-gradient(ellipse,#173327,#33513a 70%,#b9a373 74%,#685a30 80%);}
.lb-shaker-glass{position:absolute;bottom:19px;left:2%;right:2%;height:111px;border-radius:46% 46% 22% 22% / 39% 39% 13% 13%;z-index:7;
 background:linear-gradient(100deg,#e3f7dc0d,#d8eddd06 13%,#e8f8e22c 18%,#edfbe002 25%,transparent 63%,#e8f8e61f 87%,#e8f8e90e),linear-gradient(180deg,#f4ffe00b,transparent 64%,#e3efd519);
 border:1px solid #e3f2d733;box-shadow:inset 2px 0 4px #edfadf16,inset -2px 1px 3px #edfadf12;pointer-events:none;}
.lb-shaker-glass:before{content:'';position:absolute;inset:6px 10px 38%;border-top:2px solid #f3ffe442;border-radius:50%;transform:rotate(-14deg);}
.lb-shaker-glass:after{content:'';position:absolute;width:8%;height:55%;left:15%;top:17%;border-radius:80%;background:#f3ffea33;filter:blur(1px);transform:rotate(5deg);}
.lb-cube{--rx:-21deg;--ry:-29deg;--rz:-3deg;position:absolute;left:calc(50% - var(--half));bottom:39px;width:var(--die);height:var(--die);transform-style:preserve-3d;z-index:4;transform:rotateX(var(--rx)) rotateY(var(--ry)) rotateZ(var(--rz));animation:lb-dice-settle 17s ease-in-out infinite;}
.lb-shaker:nth-child(2) .lb-cube{--rx:-18deg;--ry:132deg;--rz:4deg;animation-delay:-4.8s;}.lb-shaker:nth-child(3) .lb-cube{--rx:-28deg;--ry:-64deg;--rz:-2deg;animation-delay:-9.3s;}.lb-shaker:nth-child(4) .lb-cube{--rx:29deg;--ry:57deg;--rz:3deg;animation-delay:-12.7s;}
.lb-cube>span{position:absolute;inset:0;border-radius:8px;backface-visibility:hidden;border:1px solid #b6d5ed66;background:linear-gradient(135deg,#6793ad,#285574 68%,#1b3e58);box-shadow:inset 0 1px 4px #ffffff25,inset -3px -3px 6px #091c3455;}
.lb-cube.b>span{border-color:#efb7ab55;background:linear-gradient(135deg,#c27d72,#8c393e 68%,#59232e);box-shadow:inset 0 1px 4px #ffffff20,inset -3px -3px 6px #300a1455;}
.lb-cube .f1{transform:translateZ(var(--half));}.lb-cube .f2{transform:rotateY(90deg) translateZ(var(--half));}
.lb-cube .f3{transform:rotateY(180deg) translateZ(var(--half));}.lb-cube .f4{transform:rotateY(-90deg) translateZ(var(--half));}
.lb-cube .f5{transform:rotateX(90deg) translateZ(var(--half));}.lb-cube .f6{transform:rotateX(-90deg) translateZ(var(--half));}
.lb-pip{position:absolute;width:15%;height:15%;margin:-7.5%;border-radius:50%;background:radial-gradient(circle at 55% 60%,#f3f1d9,#d4dece 70%,#818f88);box-shadow:inset 1px 1px 2px #19334890,0 1px 0 #ffffff27;}
.lb-shaker-label{position:absolute;bottom:-13px;left:0;right:0;text-align:center;font-family:var(--rr-mono);font-size:.44rem;letter-spacing:.12em;color:#b5c9b4;}
.lb-bacbo-layout{position:absolute;bottom:30px;left:15%;right:15%;display:grid;grid-template-columns:1fr .7fr 1fr;z-index:4;}
.lb-bacbo-layout span{text-align:center;padding:7px 4px;border:1px solid #b4c39330;font-family:Georgia,serif;font-size:.54rem;letter-spacing:.12em;color:#d5d4b380;}
.lb-bacbo-layout span:first-child{border-radius:10px 0 0 10px;color:#a5c5d78f;}.lb-bacbo-layout span:last-child{border-radius:0 10px 10px 0;color:#e4afa28f;}
@keyframes lb-dice-settle{0%,55%,100%{transform:rotateX(var(--rx)) rotateY(var(--ry)) rotateZ(var(--rz))}61%{transform:translateY(-4px) rotateX(calc(var(--rx) + 176deg)) rotateY(calc(var(--ry) + 99deg)) rotateZ(calc(var(--rz) + 11deg))}68%{transform:translateY(-2px) rotateX(calc(var(--rx) + 360deg)) rotateY(calc(var(--ry) + 360deg)) rotateZ(var(--rz))}74%,99%{transform:rotateX(calc(var(--rx) + 360deg)) rotateY(calc(var(--ry) + 360deg)) rotateZ(var(--rz))}}
@media(max-width:1100px){.lb-hero{gap:20px;}.lb-sub{max-width:260px;font-size:.8rem;}.lb-cena{height:280px;}.lb-info{padding:19px 17px;}.lb-shakers{gap:6px;}.lb-shaker{--die:40px;--half:20px;height:134px;}.lb-shaker-glass{height:100px;}.lb-card-top{inset:15px 16px auto;}}
@media(max-width:850px){.lb-hero{display:block;margin:24px 0;}.lb-sub{max-width:440px;margin-top:18px;}.lb-cena{height:265px;}.lb-shaker{--die:35px;--half:17.5px;}.lb-shaker-glass{height:95px;}.lb-card-format{font-size:.47rem;}.lb-nome{font-size:1.65rem;}.lb-desc{min-height:40px;}}
@media(max-width:700px){.lb-barra{padding-bottom:17px;}.lb-assinatura{font-size:.6rem;letter-spacing:.13em;}.lb-edicao{font-size:.46rem;}.lb-hero{margin:22px 0 25px;}.lb-titulo{font-size:2.7rem;}.lb-sub{font-size:.8rem;margin-top:15px;}.lb-topo{margin-bottom:20px;}.lb-cena{height:284px;}.lb-info{padding:20px 19px;}.lb-desc{min-height:0;}.lb-shakers{max-width:345px;gap:7px;}.lb-shaker{--die:42px;--half:21px;height:137px;}.lb-shaker-glass{height:106px;}.lb-rodape{display:block;margin-top:18px;padding-top:17px;font-size:.65rem;}.lb-rodape b{display:block;margin-top:10px;}.lb-pill{font-size:.56rem;}.lb-stage-code{font-size:.43rem;}}
@media(max-width:380px){.lb-titulo{font-size:2.3rem;}.lb-edicao{display:none;}.lb-cena{height:265px;}.lb-shaker{--die:35px;--half:17.5px;}.lb-shaker-glass{height:94px;}.lb-shakers{gap:4px;}.lb-nome{font-size:1.6rem;}}
@media(prefers-reduced-motion:reduce){.lb-rotor,.lb-ball-orbit,.lb-cube{animation:none!important;}.lb-card{transition:none;}}
"""

def _svg_roleta_realista() -> str:
    """37 setores na ordem europeia. A decoração não representa um giro real."""
    def ponto(raio, angulo):
        rad = math.radians(angulo)
        return 250 + raio*math.sin(rad), 250 - raio*math.cos(rad)

    def arco(raio_externo, raio_interno, inicio, fim):
        a, b, c, d = ponto(raio_externo, inicio), ponto(raio_externo, fim), ponto(raio_interno, fim), ponto(raio_interno, inicio)
        return (f'M {a[0]:.3f} {a[1]:.3f} A {raio_externo} {raio_externo} 0 0 1 {b[0]:.3f} {b[1]:.3f} '
                f'L {c[0]:.3f} {c[1]:.3f} A {raio_interno} {raio_interno} 0 0 0 {d[0]:.3f} {d[1]:.3f} Z')

    defs = ('<defs><radialGradient id="lb-gold"><stop offset="0" stop-color="#fff0bd"/>'
            '<stop offset=".45" stop-color="#d2b46e"/><stop offset=".7" stop-color="#85602f"/>'
            '<stop offset=".9" stop-color="#e6cf92"/><stop offset="1" stop-color="#82623a"/></radialGradient>'
            '<linearGradient id="lb-wood" x2="1" y2="1"><stop stop-color="#a36c3e"/>'
            '<stop offset=".27" stop-color="#56341c"/><stop offset=".54" stop-color="#815332"/>'
            '<stop offset=".8" stop-color="#3a2416"/><stop offset="1" stop-color="#67452b"/></linearGradient>'
            '<radialGradient id="lb-bowl"><stop stop-color="#9f6538"/><stop offset=".55" stop-color="#765035"/>'
            '<stop offset=".8" stop-color="#4b301e"/><stop offset="1" stop-color="#251d13"/></radialGradient>'
            '<radialGradient id="lb-ball"><stop offset="0" stop-color="#fffdf0"/>'
            '<stop offset=".45" stop-color="#eee9d6"/><stop offset="1" stop-color="#93998d"/></radialGradient>'
            '<linearGradient id="lb-shine" x2=".8" y2="1"><stop stop-color="#fef2c8" stop-opacity=".23"/>'
            '<stop offset=".36" stop-color="#fff3c4" stop-opacity="0"/><stop offset=".82" stop-color="#080d06" stop-opacity=".2"/>'
            '<stop offset="1" stop-color="#e3caa2" stop-opacity=".08"/></linearGradient></defs>')
    frame = ('<svg class="lb-frame" viewBox="0 0 500 500" aria-hidden="true">' + defs +
             '<circle cx="250" cy="250" r="239" fill="#20160e"/>'
             '<circle cx="250" cy="250" r="235" fill="url(#lb-gold)"/>'
             '<circle cx="250" cy="250" r="229" fill="url(#lb-wood)" stroke="#261c11" stroke-width="2"/>'
             '<circle cx="250" cy="250" r="219" fill="none" stroke="#d5b679" stroke-opacity=".37" stroke-width="1"/>'
             '<circle cx="250" cy="250" r="214" fill="url(#lb-gold)"/>'
             '<circle cx="250" cy="250" r="208" fill="#171b13"/>'
             '<circle cx="250" cy="250" r="202" fill="none" stroke="#8a784d" stroke-width="2"/>'
             '<circle cx="250" cy="250" r="191" fill="url(#lb-gold)"/>'
             '<circle cx="250" cy="250" r="188" fill="#1b2319"/></svg>')
    setores, passo = [], 360/37
    for i, numero in enumerate(RODA_EUROPEIA):
        inicio, fim, meio = i*passo-passo/2, (i+1)*passo-passo/2, i*passo
        cor = '#34784e' if numero == 0 else ('#a63a45' if numero in NUMEROS_VERMELHOS else '#17221b')
        setores.append(f'<g class="lb-pocket" data-numero="{numero}"><path d="{arco(187,148,inicio,fim)}" '
                       f'fill="{cor}" stroke="#bfa365" stroke-width=".9"/>')
        x, y = ponto(173, meio)
        setores.append(f'<text x="{x:.3f}" y="{y:.3f}" text-anchor="middle" dominant-baseline="middle" '
                       f'transform="rotate({meio:.3f} {x:.3f} {y:.3f})" '
                       f'font-family="Georgia,serif" font-size="13" fill="#f6ebd1">{numero}</text>')
        setores.append(f'<path d="{arco(157,148,inicio+.7,fim-.7)}" fill="#040b06" fill-opacity=".43"/></g>')
    bowl = ('<circle cx="250" cy="250" r="146" fill="url(#lb-bowl)" stroke="#b39155" stroke-width="2"/>')
    for raio in (140, 132, 122, 109, 94):
        bowl += f'<circle cx="250" cy="250" r="{raio}" fill="none" stroke="#c79b63" stroke-opacity=".12"/>'
    for a in range(0, 360, 45):
        x, y = ponto(145, a)
        bowl += f'<path d="M250 250L{x:.2f} {y:.2f}" stroke="#241b12" stroke-opacity=".38" stroke-width="1.8"/>'
    rotor = '<svg class="lb-rotor" viewBox="0 0 500 500" aria-hidden="true">' + ''.join(setores) + bowl + '</svg>'
    spindle = ('<svg class="lb-spindle" viewBox="0 0 500 500" aria-hidden="true">'
               '<ellipse cx="250" cy="260" rx="43" ry="40" fill="#130f08" opacity=".4"/>'
               '<circle cx="250" cy="250" r="39" fill="url(#lb-gold)" stroke="#4b3c21" stroke-width="2"/>'
               '<path d="M218 248 Q250 164 282 248 Q250 273 218 248" fill="url(#lb-gold)" stroke="#8e6d38"/>'
               '<path d="M217 218 L283 218 M250 185 L250 250" stroke="#41351d" stroke-width="9" stroke-linecap="round"/>'
               '<path d="M217 215 L283 215 M250 181 L250 247" stroke="url(#lb-gold)" stroke-width="7" stroke-linecap="round"/>'
               '<circle cx="250" cy="213" r="12" fill="url(#lb-gold)"/>'
               '<circle cx="215" cy="215" r="5" fill="#e7d3a1"/><circle cx="285" cy="215" r="5" fill="#b7985d"/>'
               '<circle cx="250" cy="181" r="6" fill="#f1db9f"/></svg>')
    ball = ('<svg class="lb-ball-orbit" viewBox="0 0 500 500" aria-hidden="true">'
            '<ellipse cx="250" cy="48" rx="8" ry="6" fill="#040905" opacity=".7"/>'
            '<circle cx="250" cy="43" r="7.5" fill="url(#lb-ball)"/><circle cx="247.5" cy="40" r="2" fill="#fffdf4"/></svg>')
    gloss = ('<svg class="lb-gloss" viewBox="0 0 500 500" aria-hidden="true">'
             '<circle cx="250" cy="250" r="235" fill="url(#lb-shine)"/>'
             '<path d="M75 117A222 222 0 0 1 350 50" fill="none" stroke="#fff5cf" stroke-opacity=".33" stroke-width="1.5"/></svg>')
    return '<div class="lb-wheel-wrap"><div class="lb-wheel-shadow"></div><div class="lb-wheel-base"></div><div class="lb-wheel">' + frame + rotor + spindle + ball + gloss + '</div></div>'

def _dados_realistas() -> str:
    dados = []
    for i in range(4):
        faces = []
        for nome, (valor, _) in FACES_DADO.items():
            pontos = ''.join(f'<i class="lb-pip" style="left:{x}%;top:{y}%"></i>' for x, y in PONTOS_DADO[valor])
            faces.append(f'<span class="{nome}">{pontos}</span>')
        dados.append('<div class="lb-shaker"><div class="lb-shaker-base"></div>'
                     f'<div class="lb-cube {"p" if i < 2 else "b"}">{"".join(faces)}</div>'
                     '<div class="lb-shaker-glass"></div>'
                     f'<div class="lb-shaker-label">{"PLAYER" if i < 2 else "BANKER"} {i%2+1}</div></div>')
    return '<div class="lb-felt-oval"></div><div class="lb-shakers">' + ''.join(dados) + '</div><div class="lb-bacbo-layout"><span>PLAYER</span><span>TIE</span><span>BANKER</span></div>'



def _tela_inicial(st, sessao: SessaoWeb, no_meu_pc: bool) -> str:
    """Toda vez que o painel abre (ou a página recarrega), começa no lobby: você escolhe a mesa."""
    if "rr_tela" not in st.session_state:
        st.session_state["rr_tela"] = "lobby"
    return st.session_state["rr_tela"]


def _entrar_no_jogo(jogo: str) -> None:
    import streamlit as st
    st.session_state["rr_jogo_escolhido"] = jogo
    st.session_state["rr_tela"] = "painel"


def _ir_para_lobby() -> None:
    import streamlit as st
    st.session_state["rr_tela"] = "lobby"


class HtmlLobby:
    @staticmethod
    def topo() -> str:
        logo = ('<svg viewBox="0 0 32 32" aria-hidden="true"><circle cx="16" cy="16" r="14" fill="none" stroke="#c8ad74" stroke-width="1"/>'
                '<circle cx="16" cy="16" r="9" fill="none" stroke="#c8ad74" stroke-width=".7"/>'
                '<path d="M16 2V7M30 16H25M16 30V25M2 16H7M6 6L10 10M26 6L22 10M26 26L22 22M6 26L10 22" stroke="#c8ad74" stroke-width="1"/>'
                '<circle cx="16" cy="16" r="2" fill="#c8ad74"/></svg>')
        return ('<div class="lb-topo"><div class="lb-barra"><div class="lb-assinatura">' + logo +
                'MESA DE ANÁLISE</div><div class="lb-edicao">ROLETA &amp; BAC BO</div></div>'
                '<div class="lb-hero"><div><div class="lb-kicker">Uma nova perspectiva da sua sessão</div>'
                '<h1 class="lb-titulo">Sua próxima análise<br>começa <em>aqui.</em></h1></div>'
                '<p class="lb-sub">Escolha a mesa. Acompanhe cada rodada, compare os padrões e mantenha sua sessão à vista.</p></div>'
                '<div class="lb-divisor">ESCOLHA SUA MESA</div></div>')

    @staticmethod
    def _pills(itens: List[Tuple[str, bool]]) -> str:
        return '<div class="lb-linha">' + ''.join(
            f'<span class="lb-pill{" on" if ligado else ""}"><i></i>{html.escape(texto)}</span>' for texto, ligado in itens) + '</div>'

    @classmethod
    def roleta(cls, pills: List[Tuple[str, bool]]) -> str:
        return ('<div class="lb-card lb-roleta"><div class="lb-card-top"><span class="lb-card-index">01 / ROLETA</span>'
                '<span class="lb-card-format">EUROPEIA · 37 CASAS</span></div><div class="lb-cena" aria-hidden="true">' +
                _svg_roleta_realista() + '<div class="lb-chip-stack"></div><span class="lb-stage-code">ZERO ÚNICO / 0—36</span>'
                '<span class="lb-stage-mark">European wheel</span></div><div class="lb-info"><div class="lb-info-top">'
                '<div class="lb-nome">Roleta europeia</div><span class="lb-arrow">↗</span></div>'
                '<div class="lb-desc">Cor, dúzias e colunas. Cada giro à vista.</div>' + cls._pills(pills) + '</div></div>')

    @classmethod
    def bacbo(cls, pills: List[Tuple[str, bool]]) -> str:
        return ('<div class="lb-card lb-bacbo"><div class="lb-card-top"><span class="lb-card-index">02 / BAC BO</span>'
                '<span class="lb-card-format">QUATRO DADOS</span></div><div class="lb-cena" aria-hidden="true">' +
                _dados_realistas() + '<span class="lb-stage-code">PLAYER × BANKER</span><span class="lb-stage-mark">Dice table</span>'
                '</div><div class="lb-info"><div class="lb-info-top"><div class="lb-nome">Bac Bo</div><span class="lb-arrow">↗</span></div>'
                '<div class="lb-desc">Quatro dados. Dois lados. Rodada por rodada.</div>' + cls._pills(pills) + '</div></div>')



def tela_lobby(st, sessao: SessaoWeb, no_meu_pc: bool) -> None:
    st.markdown(HtmlLobby.topo(), unsafe_allow_html=True)
    motor = sessao.motor
    pills_roleta = [("Lendo ao vivo" if sessao.leitor_ativo() else ("Simulando" if sessao.sim["rodando"] else "Parada"),
                     sessao.leitor_ativo() or sessao.sim["rodando"]),
                    (f"Banca {formatar_reais(motor.banca.saldo)}", False),
                    (f"{motor.banca.total().sinais} entradas na sessão", False)]
    bb = getattr(sessao, "bacbo", None)
    if bb is not None:
        lendo = bb.leitor_ativo()
        pills_bacbo = [("Lendo ao vivo" if lendo else ("Simulando" if bb.sim["rodando"] else "Parada"), lendo or bb.sim["rodando"]),
                       (f"Banca {formatar_reais(bb.motor.banca.saldo)}", False),
                       (f"{bb.motor.banca.total().sinais} entradas na sessão", False)]
    else:
        banca = _banca_salva("bacbo") if no_meu_pc else ConfigBacBo().banca_inicial
        pills_bacbo = [("Parada", False), (f"Banca {formatar_reais(banca)}", False), ("0 entradas na sessão", False)]
    esquerda, direita = st.columns(2, gap="large")
    with esquerda:
        st.markdown(HtmlLobby.roleta(pills_roleta), unsafe_allow_html=True)
        st.button("Entrar na Roleta", key="lb_roleta", type="primary", use_container_width=True, on_click=_entrar_no_jogo, args=(JOGO_ROLETA,))
    with direita:
        st.markdown(HtmlLobby.bacbo(pills_bacbo), unsafe_allow_html=True)
        st.button("Entrar no Bac Bo", key="lb_bacbo", type="primary", use_container_width=True, on_click=_entrar_no_jogo, args=(JOGO_BACBO,))
    rodape = ("A mesa que estiver sendo lida continua lendo enquanto você está aqui no lobby." if no_meu_pc else
              "O robô só observa. Nenhuma aposta é feita: todos os valores são de uma banca fictícia.")
    st.markdown(f'<div class="lb-rodape"><span>{html.escape(rodape)}</span><b>PRÉVIA ILUSTRATIVA DAS MESAS</b></div>', unsafe_allow_html=True)


# -----------------------------------------------------------------------------------
# Som
# -----------------------------------------------------------------------------------
JS_SOM = r"""<!doctype html><html><head><meta charset="utf-8"></head><body><script>
(function () {
  const eventos = __EVENTOS__;
  // O som é feito na página do painel (a "mãe" deste quadro invisível): ela já recebeu os seus
  // cliques, então o navegador deixa tocar, e o mesmo áudio é reaproveitado entre um sinal e outro.
  let alvo = window;
  try { if (window.parent !== window && window.parent.document) alvo = window.parent; } catch (e) {}
  let tocados = [];
  try { tocados = JSON.parse(alvo.localStorage.getItem('rr_sons') || '[]'); } catch (e) {}
  const novos = eventos.filter(e => !tocados.includes(e.id));
  if (!novos.length) return;
  try { alvo.localStorage.setItem('rr_sons', JSON.stringify(tocados.concat(novos.map(e => e.id)).slice(-80))); } catch (e) {}
  const Ctx = alvo.AudioContext || alvo.webkitAudioContext;
  if (!Ctx) return;
  let ctx = alvo.__rrAudio;
  if (!ctx || ctx.state === 'closed') { ctx = new Ctx(); alvo.__rrAudio = ctx; }
  const saida = ctx.createGain();
  saida.gain.value = 0.32;
  saida.connect(ctx.destination);
  function nota(freq, ini, dur, tipo, vol) {
    const o = ctx.createOscillator(), g = ctx.createGain();
    o.type = tipo; o.frequency.setValueAtTime(freq, ini);
    g.gain.setValueAtTime(0.0001, ini);
    g.gain.exponentialRampToValueAtTime(vol, ini + 0.012);
    g.gain.exponentialRampToValueAtTime(0.0001, ini + dur);
    o.connect(g); g.connect(saida); o.start(ini); o.stop(ini + dur + 0.05);
  }
  const SONS = {
    sinal: t => { nota(1046.5, t, 0.5, 'sine', 0.9); nota(2093, t, 0.3, 'sine', 0.22);
                  nota(1568, t + 0.16, 0.75, 'sine', 0.9); nota(3136, t + 0.16, 0.4, 'sine', 0.18); return 0.95; },
    green: t => { [523.25, 659.25, 783.99, 1046.5].forEach((f, i) => nota(f, t + i * 0.09, 0.45, 'triangle', 0.7)); return 0.85; },
    loss:  t => { nota(311.13, t, 0.35, 'triangle', 0.7); nota(233.08, t + 0.2, 0.6, 'triangle', 0.7); return 0.85; },
    empate: t => { nota(783.99, t, 0.28, 'sine', 0.6); nota(987.77, t + 0.14, 0.4, 'sine', 0.6); return 0.6; },
  };
  const tocar = () => { let t = ctx.currentTime + 0.05; for (const e of novos) t += (SONS[e.tipo] || SONS.sinal)(t); };
  if (ctx.state === 'running') tocar(); else ctx.resume().then(tocar).catch(() => {});
})();
</script></body></html>"""


def _testar_som() -> None:
    import streamlit as st
    st.session_state["rr_som_teste"] = time.time()


def _som_lateral(st) -> dict:
    """Opções de som na barra lateral."""
    st.markdown('<div class="rr-sub" style="margin-top:14px">Som</div>', unsafe_allow_html=True)
    sinais = st.checkbox("Tocar quando sair um sinal", value=True, key="rr_som_sinais")
    resultados = st.checkbox("Tocar no GREEN e no LOSS", value=False, key="rr_som_resultados")
    st.button("Testar som", key="rr_som_testar", on_click=_testar_som)
    return {"sinais": bool(sinais), "resultados": bool(resultados)}


def _id_tempo(horario: datetime) -> str:
    return f"{horario.timestamp():.3f}"


def _eventos_som_roleta(motor: MotorWeb, som: Optional[dict]) -> List[dict]:
    som = som or {}
    eventos = []
    if som.get("resultados") and motor.resultados:
        r = motor.resultados[-1]
        tipo = "green" if r.status.startswith("GREEN") else ("loss" if r.status == "LOSS" else "empate")
        eventos.append({"id": f"rr-r-{_id_tempo(r.giro.horario)}-{r.sinal.tipo}", "tipo": tipo})
    if som.get("sinais") and motor.pendentes and motor.historico:
        tipos = "-".join(s.tipo for s in motor.pendentes)
        eventos.append({"id": f"rr-s-{_id_tempo(motor.historico[-1].horario)}-{tipos}", "tipo": "sinal"})
    return eventos


def _eventos_som_bacbo(motor: MotorBacBo, som: Optional[dict]) -> List[dict]:
    som = som or {}
    eventos = []
    if som.get("resultados") and motor.resultados:
        r = motor.resultados[-1]
        eventos.append({"id": f"bb-r-{_id_tempo(r.rodada.horario)}", "tipo": {"GREEN": "green", "LOSS": "loss"}.get(r.status, "empate")})
    if som.get("sinais") and motor.pendentes and motor.historico:
        eventos.append({"id": f"bb-s-{_id_tempo(motor.historico[-1].horario)}-{motor.pendentes[0].alvo}", "tipo": "sinal"})
    return eventos


def _tocar_sons(st, eventos: List[dict]) -> None:
    """Fica no fim do painel ao vivo. Só aparece quando há algo para tocar."""
    teste = st.session_state.get("rr_som_teste")
    if teste and time.time() - teste < 8:
        eventos = list(eventos) + [{"id": f"teste-{teste:.3f}", "tipo": "sinal"}]
    if not eventos:
        return
    import streamlit.components.v1 as componentes
    pagina = JS_SOM.replace("__EVENTOS__", json.dumps(eventos)).replace("<head>", "<head><title>rr-som</title>")
    componentes.html(pagina, height=0)


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


# ===================================================================================
# 14) PESQUISA DE PADRÕES, VALIDAÇÃO CRONOLÓGICA E ACOMPANHAMENTO EM OBSERVAÇÃO
# -----------------------------------------------------------------------------------
# Hipóteses experimentais. Nenhum padrão abaixo altera a probabilidade de uma mesa
# justa/independente. Fontes e hipóteses estatísticas: FONTES_E_METODOLOGIA.md.
# O motor original permanece disponível para reproduzir os testes de aceitação.
# ===================================================================================
VERSAO_ANALISE = "2.0.0-pesquisa"
LIMITE_REGISTROS_PESQUISA = 200_000
FONTES_PESQUISA = {
    "Evolution — regras do Bac Bo": "https://games.evolution.com/live-casino/live-craps-and-dice/bac-bo/",
    "Operador — pagamentos do Bac Bo": "https://www.cloudbet.com/pt-br/casino/play/evolution/ev_bac_bo",
    "NIST — intervalo de Wilson": "https://www.itl.nist.gov/div898/handbook/prc/section2/prc241.htm",
    "NIST — comparações múltiplas": "https://www.itl.nist.gov/div898/handbook/prc/section4/prc473.htm",
    "Hoeffding (1963) — retornos limitados": "https://www.tandfonline.com/doi/abs/10.1080/01621459.1963.10500830",
    "Gambling Commission — retorno e vantagem da casa":
        "https://www.gamblingcommission.gov.uk/public-and-players/guide/return-to-player-how-much-gaming-machines-payout/",
}


@dataclass(frozen=True)
class ConfigPesquisa:
    valor_por_alvo: float = 10.0
    protecao: float = 0.0
    banca_inicial: float = 1000.0
    minimo_sinais: int = 200
    meta_acerto: float = 0.60
    alpha: float = 0.05
    exposicao_maxima: float = 0.02
    stop_loss: float = 0.10
    stop_gain: float = 0.10

    def __post_init__(self) -> None:
        valores = (self.valor_por_alvo, self.protecao, self.banca_inicial, self.meta_acerto,
                   self.alpha, self.exposicao_maxima, self.stop_loss, self.stop_gain)
        if any(isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v) for v in valores):
            raise ValueError("Use valores numéricos finitos na configuração de pesquisa.")
        if self.valor_por_alvo <= 0 or self.protecao < 0 or self.banca_inicial <= 0:
            raise ValueError("Banca e ficha precisam ser positivas; proteção não pode ser negativa.")
        if isinstance(self.minimo_sinais, bool) or not isinstance(self.minimo_sinais, int) or self.minimo_sinais < 30:
            raise ValueError("O mínimo precisa ser um inteiro de pelo menos 30 sinais por período.")
        if not 0.60 <= self.meta_acerto < 1 or not 0 < self.alpha < 0.5:
            raise ValueError("A meta precisa estar entre 60% e 100% exclusivo; alpha entre 0 e 0,5.")
        if any(not 0 < v <= 1 for v in (self.exposicao_maxima, self.stop_loss, self.stop_gain)):
            raise ValueError("Os limites de exposição e de parada precisam estar entre 0 e 100%.")


@dataclass(frozen=True)
class RegistroPesquisa:
    identificador: str
    mesa: str
    evento: object
    horario: Optional[datetime] = None
    origem: str = "informado"


@dataclass(frozen=True)
class AlvoPesquisa:
    familia: str
    alvos: tuple


@dataclass(frozen=True)
class PadraoPesquisa:
    chave: str
    jogo: str
    nome: str
    familia: str
    gatilho: int
    modo: str

    def prever(self, historico: list) -> Optional[AlvoPesquisa]:
        """Usa SOMENTE o passado. O alvo retornado vale para a rodada seguinte."""
        if len(historico) < self.gatilho:
            return None
        if self.jogo == "bacbo":
            valores = [r.resultado for r in historico]
            if self.modo == "pos_empate":
                return AlvoPesquisa("bacbo", (EMPATE,)) if valores[-1] == EMPATE else None
            if self.modo == "retomar":
                return (AlvoPesquisa("bacbo", (valores[-2],))
                        if valores[-1] == EMPATE and valores[-2] in OPOSTO else None)
            pares = (PLAYER, BANKER)
        else:
            valores = [_valor_familia(g, self.familia) for g in historico]
            pares = (VERMELHO, PRETO) if self.familia == "cor" else (0, 1)
        ultimo = valores[-1]
        if ultimo is None or ultimo == EMPATE:
            return None
        n = 0
        for v in reversed(valores):
            if v != ultimo:
                break
            n += 1
        if self.modo in ("seguir", "inverter", "cobrir"):
            if n != self.gatilho:
                return None
            if self.modo == "cobrir":
                alvos = tuple(v for v in (1, 2, 3) if v != ultimo)
            elif self.modo == "seguir":
                alvos = (ultimo,)
            else:
                alvos = (pares[1] if ultimo == pares[0] else pares[0],)
        elif self.modo in ("alternar", "quebrar"):
            n = 1
            while (n < len(valores) and valores[-1-n] not in (None, EMPATE)
                   and valores[-1-n] != valores[-n]):
                n += 1
            if n != self.gatilho:
                return None
            alvos = (ultimo if self.modo == "quebrar" else
                     (pares[1] if ultimo == pares[0] else pares[0]),)
        elif self.modo in ("duplas", "triplas"):
            k = self.gatilho // 2
            a, b = valores[-2*k:-k], valores[-k:]
            if (None in a + b or EMPATE in a + b or len(set(a)) != 1
                    or len(set(b)) != 1 or a[0] == b[0] or n != k):
                return None
            alvos = (a[0],)
        else:
            raise ValueError(f"Modo de padrão desconhecido: {self.modo}")
        return AlvoPesquisa("bacbo" if self.jogo == "bacbo" else self.familia, alvos)


def _valor_familia(giro: Giro, familia: str):
    if giro.numero == 0:
        return None
    if familia == "paridade":
        return giro.numero % 2  # 0 = par, 1 = ímpar
    if familia == "metade":
        return int(giro.numero > 18)
    return getattr(giro, familia)


def catalogo_pesquisa(jogo: str) -> List[PadraoPesquisa]:
    """Catálogo fixo antes da divisão dos dados; sem mineração do conjunto de teste."""
    if jogo not in ("roleta", "bacbo"):
        raise ValueError("Escolha roleta ou bacbo.")
    linhas = []
    if jogo == "roleta":
        for n in (3, 4, 5):
            linhas.append((f"cor_inv{n}", f"Cor: {n} iguais → oposta", "cor", n, "inverter"))
        for n in (3, 4):
            linhas.append((f"cor_seg{n}", f"Cor: {n} iguais → mesma", "cor", n, "seguir"))
        for n in (4, 6):
            linhas.extend([(f"cor_alt{n}", f"Cor: alternância {n} → continua", "cor", n, "alternar"),
                           (f"cor_quebra{n}", f"Cor: alternância {n} → quebra", "cor", n, "quebrar")])
        for familia, nome in (("duzia", "Dúzia"), ("coluna", "Coluna")):
            for n in (3, 4):
                linhas.append((f"{familia}_cob{n}", f"{nome}: {n} iguais → outras duas", familia, n, "cobrir"))
            linhas.append((f"{familia}_seg3", f"{nome}: 3 iguais → mesma", familia, 3, "seguir"))
        for familia, nome in (("paridade", "Par/ímpar"), ("metade", "1–18/19–36")):
            for modo, texto in (("inverter", "inverte"), ("seguir", "repete")):
                linhas.append((f"{familia}_{modo}4", f"{nome}: 4 iguais → {texto}", familia, 4, modo))
    else:
        for n in (3, 4, 5):
            linhas.append((f"bb_inv{n}", f"{n} iguais → lado oposto", "bacbo", n, "inverter"))
        for n in (2, 3, 4, 5):
            linhas.append((f"bb_seg{n}", f"{n} iguais → mesmo lado", "bacbo", n, "seguir"))
        for n in (4, 6):
            linhas.extend([(f"bb_alt{n}", f"Alternância {n} → continua", "bacbo", n, "alternar"),
                           (f"bb_quebra{n}", f"Alternância {n} → quebra", "bacbo", n, "quebrar")])
        linhas.extend([("bb_duplas", "Duplas PPBB/BBPP → primeiro lado", "bacbo", 4, "duplas"),
                       ("bb_triplas", "Triplas PPPBBB/BBBPPP → primeiro lado", "bacbo", 6, "triplas"),
                       ("bb_emp", "Empate → novo empate", "bacbo", 1, "pos_empate"),
                       ("bb_retomar", "Após empate → retoma lado anterior", "bacbo", 2, "retomar")])
    return [PadraoPesquisa(c, jogo, nome, f, g, m) for c, nome, f, g, m in linhas]


def liquidar_pesquisa(evento, alvo: AlvoPesquisa, config: ConfigPesquisa) -> tuple:
    """(acerto do alvo principal, lucro líquido ou None, exposição total)."""
    ficha, protecao = config.valor_por_alvo, config.protecao
    if alvo.familia != "bacbo":
        acertou = _valor_familia(evento, alvo.familia) in alvo.alvos
        multiplicador = 3 if alvo.familia in ("duzia", "coluna") else 2
        apostado = ficha * len(alvo.alvos) + protecao
        retorno = ficha * multiplicador if acertou else 0.0
        if evento.numero == 0:
            retorno += 36 * protecao
        return acertou, retorno - apostado, apostado
    lado = alvo.alvos[0]
    acertou = evento.resultado == lado
    if lado == EMPATE:
        if acertou and evento.soma_vencedora is None:
            return True, None, ficha
        retorno = ficha * (PAGA_EMPATE[evento.soma_vencedora] + 1) if acertou else 0.0
        return acertou, retorno - ficha, ficha
    apostado = ficha + protecao
    if evento.resultado == EMPATE:
        if protecao > 0 and evento.soma_vencedora is None:
            return False, None, apostado
        retorno = ficha * DEVOLUCAO_NO_EMPATE
        if protecao:
            retorno += protecao * (PAGA_EMPATE[evento.soma_vencedora] + 1)
    else:
        retorno = 2 * ficha if acertou else 0.0
    return acertou, retorno - apostado, apostado


@lru_cache(maxsize=128)
def matematica_pesquisa(alvo: AlvoPesquisa, config: ConfigPesquisa) -> dict:
    """Enumeração EXATA das 37 casas ou das 6^4 combinações de dados."""
    if alvo.familia == "bacbo":
        eventos = [RodadaBacBo.dos_dados(*d) for d in product(range(1, 7), repeat=4)]
    else:
        eventos = [Giro.a_partir_do_numero(n) for n in range(37)]
    liquidacoes = [liquidar_pesquisa(e, alvo, config) for e in eventos]
    retornos = [lucro / aposta for _, lucro, aposta in liquidacoes]
    return {"chance_alvo": sum(int(a) for a, _, _ in liquidacoes) / len(eventos),
            "chance_lucro": sum(int(l > 0) for _, l, _ in liquidacoes) / len(eventos),
            "roi_teorico": math.fsum(retornos) / len(eventos),
            "retorno_minimo": min(retornos), "retorno_maximo": max(retornos)}


def intervalo_wilson(acertos: int, total: int, alpha: float = 0.05) -> tuple:
    """Intervalo aproximado de Wilson, sob hipótese de observações independentes."""
    if not 0 <= acertos <= total or not 0 < alpha < 1:
        raise ValueError("Contagens ou alpha inválidos para o intervalo.")
    if total == 0:
        return 0.0, 1.0
    z = NormalDist().inv_cdf(1 - alpha / 2)
    p, z2 = acertos / total, z*z
    centro = (p + z2/(2*total)) / (1 + z2/total)
    raio = z * math.sqrt(p*(1-p)/total + z2/(4*total*total)) / (1 + z2/total)
    return max(0.0, centro-raio), min(1.0, centro+raio)


class MetricasPesquisa:
    def __init__(self) -> None:
        self.entradas = self.acertos = self.positivos = self.incompletas = 0
        self.apostado = self.lucro = self.pico = self.queda_maxima = 0.0
        self.sequencia_perdas = self.maior_sequencia_perdas = 0

    def registrar(self, acertou: bool, lucro: Optional[float], apostado: float) -> None:
        self.entradas += 1
        self.acertos += int(acertou)
        self.apostado += apostado
        if lucro is None:
            self.incompletas += 1
            self.sequencia_perdas = 0
            return
        self.lucro += lucro
        self.positivos += int(lucro > 0)
        self.pico = max(self.pico, self.lucro)
        self.queda_maxima = max(self.queda_maxima, self.pico - self.lucro)
        self.sequencia_perdas = self.sequencia_perdas + 1 if lucro < 0 else 0
        self.maior_sequencia_perdas = max(self.maior_sequencia_perdas, self.sequencia_perdas)

    def resumo(self, matematica: dict, alpha_corrigido: float) -> dict:
        n = self.entradas
        exato = self.incompletas == 0
        roi = self.lucro / self.apostado if self.apostado and exato else None
        penalidade = ((matematica["retorno_maximo"] - matematica["retorno_minimo"])
                      * math.sqrt(math.log(1/alpha_corrigido) / (2*n))) if n else None
        return {"entradas": n, "acertos_alvo": self.acertos,
                "acerto": self.acertos/n if n else None,
                "acerto_limite_conservador": max(0.0, self.acertos/n - math.sqrt(math.log(1/alpha_corrigido)/(2*n))) if n else 0.0,
                "wilson_95": list(intervalo_wilson(self.acertos, n)),
                "wilson_corrigido": list(intervalo_wilson(self.acertos, n, alpha_corrigido)),
                "entradas_com_lucro": self.positivos if exato else None,
                "liquidacoes_incompletas": self.incompletas,
                "apostado": round(self.apostado, 6), "lucro": round(self.lucro, 6) if exato else None,
                "lucro_parcial_conhecido": round(self.lucro, 6), "roi": roi,
                "roi_limite_inferior": roi - penalidade if roi is not None and n else None,
                "queda_maxima": round(self.queda_maxima, 6) if exato else None,
                "maior_sequencia_perdas": self.maior_sequencia_perdas if exato else None}


def _horario_csv(texto: str) -> Optional[datetime]:
    texto = texto.strip()
    if not texto:
        return None
    try:
        valor = datetime.fromisoformat(texto.replace("Z", "+00:00"))
    except ValueError:
        try:
            valor = datetime.strptime(texto, "%d/%m/%Y %H:%M:%S")
        except ValueError as erro:
            raise ValueError("Use horário ISO 8601 ou DD/MM/AAAA HH:MM:SS.") from erro
    return valor if valor.tzinfo is not None else valor.replace(tzinfo=timezone(timedelta(hours=-3)))


def importar_historico_pesquisa(dados: bytes, jogo: str) -> tuple:
    """CSV completo, do mais antigo para o mais novo. Nunca elimina resultados iguais."""
    if jogo not in ("roleta", "bacbo"):
        raise ValueError("Jogo inválido.")
    if len(dados) > 30 * 1024 * 1024:
        raise ValueError("O CSV excede o limite de 30 MB.")
    try:
        texto = dados.decode("utf-8-sig")
    except UnicodeDecodeError:
        texto = dados.decode("cp1252")
    if not texto.strip():
        raise ValueError("Arquivo vazio.")
    primeira = texto.splitlines()[0]
    separador = max((";", ",", "\t"), key=primeira.count)
    leitor = csv.DictReader(io.StringIO(texto), delimiter=separador)
    campos = leitor.fieldnames or []
    if len(campos) != len(set(campos)):
        raise ValueError("O CSV contém colunas repetidas.")
    if any(c in campos for c in ("Padrão", "Apostado (R$)", "Entrada em")):
        raise ValueError("Este é um relatório de entradas. Use o histórico completo de TODAS as rodadas.")
    necessarios = {"numero"} if jogo == "roleta" else {"resultado"}
    if not necessarios.issubset(campos):
        raise ValueError("Coluna obrigatória: " + ", ".join(sorted(necessarios)))
    registros, vistos, duplicatas = [], {}, 0
    for linha, row in enumerate(leitor, 2):
        if None in row or any(v is None for v in row.values()):
            raise ValueError(f"Linha {linha}: quantidade de colunas inválida.")
        try:
            horario = _horario_csv(row.get("horario", ""))
            mesa = row.get("mesa", "").strip() or "mesa_informada"
            identificador = row.get("id_rodada", "").strip() or f"linha-{linha}"
            origem = row.get("origem", "informado").strip() or "informado"
            if jogo == "roleta":
                evento = Giro.a_partir_do_numero(int(row["numero"].strip()), horario)
            else:
                lado = row["resultado"].strip().upper()
                lado = {"PLAYER": PLAYER, "BANKER": BANKER, "EMPATE": EMPATE, "T": EMPATE, "TIE": EMPATE}.get(lado, lado)
                soma = int(row["soma"].strip()) if row.get("soma", "").strip() else None
                if lado != EMPATE and soma == 2:
                    raise ValueError("soma vencedora 2 só é possível em empate")
                evento = RodadaBacBo.do_resultado(lado, soma, horario)
            registro = RegistroPesquisa(identificador, mesa, evento, horario, origem)
            chave = (mesa, identificador)
            assinatura = ((evento.numero,) if jogo == "roleta" else
                          (evento.resultado, evento.soma_vencedora)) + (horario, origem)
            if chave in vistos:
                if vistos[chave] != assinatura:
                    raise ValueError("mesmo ID de rodada com dados conflitantes")
                duplicatas += 1
                continue
            vistos[chave] = assinatura
            registros.append(registro)
            if len(registros) > LIMITE_REGISTROS_PESQUISA:
                raise ValueError(f"limite de {LIMITE_REGISTROS_PESQUISA} rodadas excedido")
        except (ValueError, TypeError) as erro:
            raise ValueError(f"Linha {linha}: {erro}") from erro
    validar_registros_pesquisa(registros, jogo)
    avisos = [f"{duplicatas} linha(s) duplicada(s) removida(s) pelo ID da rodada."] if duplicatas else []
    if any(r.horario is None for r in registros):
        avisos.append("Sem horários: a ordem das linhas foi assumida como cronológica.")
    if any(r.identificador.startswith("linha-") for r in registros):
        avisos.append("Sem IDs completos: não é possível confirmar duplicatas entre rodadas.")
    if any(r.mesa == "mesa_informada" for r in registros):
        avisos.append("Mesa não identificada: não é possível comprovar que todas as linhas pertencem à mesma mesa.")
    return registros, avisos


def validar_registros_pesquisa(registros: list, jogo: str) -> None:
    if jogo not in ("roleta", "bacbo"):
        raise ValueError("Jogo inválido.")
    if not registros:
        raise ValueError("Não há rodadas válidas.")
    if len(registros) > LIMITE_REGISTROS_PESQUISA:
        raise ValueError("Histórico acima do limite de 200.000 rodadas.")
    if len({r.mesa for r in registros}) != 1:
        raise ValueError("Mesas diferentes no mesmo teste. Separe uma mesa por arquivo.")
    # O Streamlit redefine as classes em cada rerun. Validar pelos dados mantém
    # compatibilidade com instâncias legítimas guardadas pela execução anterior.
    for registro in registros:
        evento = registro.evento
        try:
            if jogo == "roleta":
                esperado = Giro.a_partir_do_numero(evento.numero)
                if (evento.cor, evento.duzia, evento.coluna) != (esperado.cor, esperado.duzia, esperado.coluna):
                    raise ValueError("classificação da roleta inconsistente")
            else:
                RodadaBacBo.do_resultado(evento.resultado, evento.soma_vencedora)
                sp, sb = evento.soma_player, evento.soma_banker
                for soma in (sp, sb):
                    if soma is not None and (isinstance(soma, bool) or not isinstance(soma, int) or not 2 <= soma <= 12):
                        raise ValueError("soma dos dados inválida")
                if sp is not None and sb is not None:
                    esperado = PLAYER if sp > sb else (BANKER if sb > sp else EMPATE)
                    if evento.resultado != esperado:
                        raise ValueError("resultado e somas conflitantes")
        except (AttributeError, ValueError, TypeError) as erro:
            raise ValueError(f"Rodada incompatível com o jogo selecionado: {erro}") from erro
    horarios = [r.horario for r in registros]
    if any(h is None for h in horarios) and any(h is not None for h in horarios):
        raise ValueError("Preencha todos os horários ou deixe todos em branco.")
    horarios = [h if h is None or h.tzinfo else h.replace(tzinfo=timezone(timedelta(hours=-3))) for h in horarios]
    if horarios[0] is not None and any(b < a for a, b in zip(horarios, horarios[1:])):
        raise ValueError("Histórico fora de ordem: envie do mais antigo para o mais novo.")
    chaves = [(r.mesa, r.identificador) for r in registros]
    if len(set(chaves)) != len(chaves):
        raise ValueError("IDs de rodada duplicados no histórico.")


def csv_historico_pesquisa(registros: list, jogo: str) -> bytes:
    cabecalho = ["id_rodada", "mesa", "horario", "origem"]
    cabecalho += ["numero"] if jogo == "roleta" else ["resultado", "soma"]
    linhas = [cabecalho]
    for r in registros:
        base = [r.identificador, r.mesa, r.horario.isoformat() if r.horario else "", r.origem]
        base += [str(r.evento.numero)] if jogo == "roleta" else [r.evento.resultado, str(r.evento.soma_vencedora or "")]
        linhas.append(base)
    return _planilha(linhas)


def simular_pesquisa(quantidade: int, semente: int, jogo: str) -> list:
    if jogo not in ("roleta", "bacbo"):
        raise ValueError("Jogo inválido.")
    if isinstance(quantidade, bool) or not isinstance(quantidade, int) or not 200 <= quantidade <= LIMITE_REGISTROS_PESQUISA:
        raise ValueError("Simule entre 200 e 200.000 rodadas.")
    rng, registros = random.Random(semente), []
    for n in range(quantidade):
        evento = (Giro.a_partir_do_numero(rng.randint(0, 36)) if jogo == "roleta" else
                  RodadaBacBo.dos_dados(*(rng.randint(1, 6) for _ in range(4))))
        registros.append(RegistroPesquisa(str(n+1), f"SIMULADA-{jogo}-{semente}", evento, None, "simulado"))
    return registros


def analisar_pesquisa(registros: list, jogo: str, config: Optional[ConfigPesquisa] = None,
                     padroes: Optional[list] = None, fonte: str = "historico_informado", ao_progredir=None) -> dict:
    """50% treino; 25% validação; 25% teste. Seleção congelada ao fim do treino.

    O teste completo é descritivo. Repetir testes/ajustar o catálogo exige um NOVO
    histórico futuro. Wilson/limite de Hoeffding assumem rodadas independentes.
    """
    config = config or ConfigPesquisa()
    validar_registros_pesquisa(registros, jogo)
    if len(registros) < 200:
        raise ValueError("São necessárias pelo menos 200 rodadas completas, em ordem cronológica.")
    padroes = list(catalogo_pesquisa(jogo) if padroes is None else padroes)
    if not padroes or len({p.chave for p in padroes}) != len(padroes) or any(p.jogo != jogo for p in padroes):
        raise ValueError("O catálogo precisa ter padrões únicos do jogo selecionado.")
    n, fim_treino, fim_validacao = len(registros), len(registros)//2, len(registros)*3//4
    # Inclui todos os possíveis tamanhos de amostra até o horizonte do arquivo.
    # Isso evita tratar a quantidade aleatória de gatilhos como um n fixado antes.
    alpha_corrigido = config.alpha / (len(padroes) * 3 * 2 * len(registros))
    metricas = {p.chave: [MetricasPesquisa(), MetricasPesquisa(), MetricasPesquisa()] for p in padroes}
    historico, pendentes, matematicas = deque(maxlen=40), {}, {}
    selecionado, curva_teste, lucro_teste = None, [(0, 0.0)], 0.0
    teste_completo = True

    def selecionar_no_treino():
        elegiveis = []
        for p in padroes:
            if p.chave not in matematicas:
                continue
            s = metricas[p.chave][0].resumo(matematicas[p.chave], alpha_corrigido)
            if s["entradas"] >= max(30, config.minimo_sinais//2) and s["roi_limite_inferior"] is not None:
                elegiveis.append((s["roi_limite_inferior"], s["entradas"], p.chave))
        return max(elegiveis)[2] if elegiveis else None

    for i, registro in enumerate(registros):
        if i == fim_treino:
            selecionado = selecionar_no_treino()
        fase = 0 if i < fim_treino else (1 if i < fim_validacao else 2)
        for chave, alvo in pendentes.items():
            acerto, lucro, aposta = liquidar_pesquisa(registro.evento, alvo, config)
            metricas[chave][fase].registrar(acerto, lucro, aposta)
            if fase == 2 and chave == selecionado:
                if lucro is None:
                    teste_completo = False
                elif teste_completo:
                    lucro_teste += lucro
                    curva_teste.append((i - fim_validacao + 1, lucro_teste))
        historico.append(registro.evento)
        pendentes = {}
        for p in padroes:
            alvo = p.prever(list(historico))
            if alvo is not None:
                pendentes[p.chave] = alvo
                if p.chave not in matematicas:
                    matematicas[p.chave] = matematica_pesquisa(alvo, config)
        if ao_progredir and (i % max(1, n//100) == 0 or i == n-1):
            ao_progredir((i+1)/n)
    linhas = []
    for p in padroes:
        # A distribuição não depende do alvo específico, por simetria da mesa.
        if p.chave not in matematicas:
            exemplo = (AlvoPesquisa("bacbo", (EMPATE if p.modo == "pos_empate" else PLAYER,))
                       if jogo == "bacbo" else AlvoPesquisa(p.familia,
                           (1, 2) if p.modo == "cobrir" else ((VERMELHO,) if p.familia == "cor" else
                              ((1,) if p.familia in ("duzia", "coluna") else (0,)))))
            matematicas[p.chave] = matematica_pesquisa(exemplo, config)
        mat = matematicas[p.chave]
        resumos = [m.resumo(mat, alpha_corrigido) for m in metricas[p.chave]]
        motivos = []
        for nome, resumo in zip(("validação", "teste"), resumos[1:]):
            if resumo["entradas"] < config.minimo_sinais:
                motivos.append(f"{nome}: amostra insuficiente")
            if resumo["liquidacoes_incompletas"]:
                motivos.append(f"{nome}: pagamento de empate incompleto")
            if resumo["wilson_corrigido"][0] <= max(config.meta_acerto, mat["chance_alvo"]):
                motivos.append(f"{nome}: limite de acerto não supera meta e referência teórica")
            if resumo["acerto_limite_conservador"] <= max(config.meta_acerto, mat["chance_alvo"]):
                motivos.append(f"{nome}: limite conservador de acerto insuficiente")
            if resumo["roi_limite_inferior"] is None or resumo["roi_limite_inferior"] <= 0:
                motivos.append(f"{nome}: retorno positivo sem evidência suficiente")
        linhas.append({"chave": p.chave, "nome": p.nome, "matematica": mat,
                       "treino": resumos[0], "validacao": resumos[1], "teste": resumos[2],
                       "criterios_numericos": not motivos, "motivos": motivos})
    escolhido = next((r for r in linhas if r["chave"] == selecionado), None)
    dados_simulados = fonte == "simulado" or any(r.origem == "simulado" for r in registros)
    origem_desconhecida = any(r.origem in ("nao_informada", "desconhecida") for r in registros)
    metadados_completos = all(r.horario is not None and not r.identificador.startswith("linha-")
                             and r.mesa != "mesa_informada" for r in registros)
    evidencia = bool(escolhido and escolhido["criterios_numericos"] and not dados_simulados
                     and not origem_desconhecida and metadados_completos)
    assinatura = hashlib.sha256(csv_historico_pesquisa(registros, jogo)).hexdigest()
    return {"versao": VERSAO_ANALISE, "jogo": jogo, "fonte": fonte, "dados_simulados": dados_simulados,
            "origem_desconhecida": origem_desconhecida, "mesa": registros[0].mesa,
            "metadados_completos": metadados_completos,
            "rodadas": n, "sha256_historico": assinatura, "config": asdict(config),
            "divisao": {"treino": [0, fim_treino], "validacao": [fim_treino, fim_validacao], "teste": [fim_validacao, n]},
            "alpha_por_comparacao": alpha_corrigido, "selecionado_no_treino": selecionado,
            "criterios_atendidos_no_historico": evidencia, "tabela": linhas,
            "curva_teste": curva_teste if teste_completo else [],
            "limites": ["Não há garantia de acerto futuro ou lucro.",
                        "Os padrões são hipóteses experimentais, não métodos comprovados pelas fontes.",
                        "Intervalos assumem rodadas independentes; Wilson é uma aproximação.",
                        "Correção cobre apenas este catálogo e esta execução; não cobre repetição de testes.",
                        "O retorno de cada padrão é contrafactual, com ficha fixa e sem limites de banca.",
                        "O acompanhamento separado aplica limites de banca, exposição e parada.",
                        "Os horários/IDs importados e a origem declarada não são autenticados pelo programa."],
            "fontes": FONTES_PESQUISA}


def motivo_risco_pesquisa(saldo: float, aposta: float, config: ConfigPesquisa) -> Optional[str]:
    if saldo <= config.banca_inicial * (1-config.stop_loss):
        return "Limite de perda atingido."
    if saldo >= config.banca_inicial * (1+config.stop_gain):
        return "Limite de ganho atingido."
    if aposta > saldo:
        return "Saldo insuficiente para a exposição total."
    if aposta > saldo * config.exposicao_maxima + 1e-9:
        return "Exposição acima do limite por rodada."
    return None


class AcompanhamentoPesquisa:
    """Uma hipótese congelada, uma entrada por rodada, APENAS EM OBSERVAÇÃO."""
    def __init__(self, padrao: PadraoPesquisa, config: ConfigPesquisa, historico: Optional[list] = None) -> None:
        self.padrao, self.config = padrao, config
        self.historico = deque(historico or [], maxlen=40)
        self.metricas = MetricasPesquisa()
        self.saldo = config.banca_inicial
        self.pendente = None
        self.motivo = "Aguardando gatilho."
        self.liquidacao_incompleta = False
        self._preparar()

    def _preparar(self) -> None:
        self.pendente = None
        if self.liquidacao_incompleta:
            self.motivo = "Observação pausada: empate sem soma; saldo final desconhecido."
            return
        alvo = self.padrao.prever(list(self.historico))
        if alvo is None:
            self.motivo = "Aguardando gatilho."
            return
        aposta = (self.config.valor_por_alvo if alvo.familia == "bacbo" and alvo.alvos == (EMPATE,) else
                  self.config.valor_por_alvo * len(alvo.alvos) + self.config.protecao)
        bloqueio = motivo_risco_pesquisa(self.saldo, aposta, self.config)
        self.motivo = bloqueio or "Gatilho em observação para a próxima rodada."
        if bloqueio is None:
            self.pendente = alvo

    def observar(self, evento) -> None:
        if self.pendente is not None:
            acerto, lucro, aposta = liquidar_pesquisa(evento, self.pendente, self.config)
            self.metricas.registrar(acerto, lucro, aposta)
            if lucro is None:
                self.liquidacao_incompleta = True
            else:
                self.saldo += lucro
        self.historico.append(evento)
        self._preparar()


def registrar_rodada_pesquisa(motor, evento, indice: int) -> None:
    if not motor.registrar:
        return  # backtests de aceitação não pagam custo de registro/pesquisa
    if len(motor.registros_pesquisa) >= LIMITE_REGISTROS_PESQUISA:
        motor.descartados_pesquisa += 1
    # ID/horário locais de captura, não IDs autenticados da mesa.
    horario = datetime.now(timezone(timedelta(hours=-3)))
    motor.registros_pesquisa.append(RegistroPesquisa(str(indice), motor.mesa_pesquisa, evento, horario,
                                                    motor.fonte_pesquisa))
    if motor.acompanhamento_pesquisa is not None:
        motor.acompanhamento_pesquisa.observar(evento)


def iniciar_registro_pesquisa(motor, jogo: str) -> None:
    motor.registros_pesquisa = deque(maxlen=LIMITE_REGISTROS_PESQUISA)
    motor.descartados_pesquisa = 0
    motor.mesa_pesquisa = f"sessao-{jogo}-{time.time_ns()}"
    motor.fonte_pesquisa = "nao_informada"
    motor.acompanhamento_pesquisa = None


def sincronizar_historico_pesquisa(motor) -> None:
    """Calibração não liquida uma entrada e invalida o desfazer de antes dela."""
    motor._foto = None
    motor._foto_pesquisa = None
    acompanhamento = getattr(motor, "acompanhamento_pesquisa", None)
    if acompanhamento is not None:
        acompanhamento.historico = deque(motor.historico, maxlen=40)
        acompanhamento._preparar()


def texto_alvo_pesquisa(alvo: AlvoPesquisa) -> str:
    if alvo.familia == "bacbo":
        return NOMES_LADO[alvo.alvos[0]]
    if alvo.familia == "cor":
        return str(alvo.alvos[0])
    if alvo.familia == "paridade":
        return "PAR" if alvo.alvos[0] == 0 else "ÍMPAR"
    if alvo.familia == "metade":
        return "1 a 18" if alvo.alvos[0] == 0 else "19 a 36"
    return ("Dúzia " if alvo.familia == "duzia" else "Coluna ") + " + ".join(str(a) for a in alvo.alvos)


def _resumo_monitor_pesquisa(st, motor, jogo: str) -> None:
    with st.expander("Análise avançada · padrões e qualidade da evidência", expanded=True):
        st.caption("Os alertas dos padrões originais são experimentais. Acerto histórico não é probabilidade da próxima rodada.")
        if jogo == "bacbo" and getattr(motor.banca, "liquidacoes_estimadas", 0):
            st.warning(f"O comparativo original tem {motor.banca.liquidacoes_estimadas} empate(s) sem soma: "
                       "usa o pagamento mínimo e seu saldo é uma estimativa. A pesquisa trata esses pagamentos como incompletos.")
        acompanhamento = motor.acompanhamento_pesquisa
        if acompanhamento is None:
            st.info("Abra Pesquisa e validação na barra lateral para testar novos padrões e acompanhar um candidato.")
        else:
            st.write(f"Em observação: **{acompanhamento.padrao.nome}**")
            st.caption(acompanhamento.motivo)
            c1, c2, c3 = st.columns(3)
            c1.metric("Entradas observadas", acompanhamento.metricas.entradas)
            n = acompanhamento.metricas.entradas
            c2.metric("Acerto do alvo", formatar_pct(acompanhamento.metricas.acertos/n) if n else "—")
            c3.metric("Saldo da observação", "Incompleto" if acompanhamento.liquidacao_incompleta else
                      formatar_reais(acompanhamento.saldo))
            if acompanhamento.pendente is not None:
                st.write("Próximo alvo em observação: **" + texto_alvo_pesquisa(acompanhamento.pendente) + "**")
        st.caption(f"Histórico completo registrado: {len(motor.registros_pesquisa):,} rodadas. "
                   "O relatório de entradas antigo continua separado.")


def _painel_pesquisa(st, sessao, jogo: str) -> None:
    motor = sessao.motor
    prefixo = "pesq_" + jogo
    st.markdown('<div class="rr-topo"><div><div class="rr-sub">Roleta e Bac Bo · v2.0</div>'
                '<div class="rr-titulo">Pesquisa e validação</div></div></div>', unsafe_allow_html=True)
    st.write("Teste hipóteses com todas as rodadas, selecione no primeiro período e confira o resultado em dois períodos posteriores.")
    st.info("Meta de acerto superior a 60%, com retorno líquido positivo e amostra suficiente. "
            "Isso é um critério de avaliação do histórico, sem garantia de desempenho futuro.")

    def captura():
        sessao.tick()
        st.caption(f"Rodadas capturadas nesta sessão: {len(motor.registros_pesquisa):,}")
    st.fragment(captura, run_every=1.0 if sessao.leitor_ativo() or sessao.sim["rodando"] else None)()
    if motor.descartados_pesquisa:
        st.warning(f"O limite de captura foi atingido: {motor.descartados_pesquisa} rodadas antigas saíram do registro.")
    fonte = st.radio("Dados para análise", ["Importar histórico CSV", "Sessão atual", "Simulação de controle"],
                     key=prefixo+"_fonte", horizontal=True)
    arquivo = None
    if fonte == "Importar histórico CSV":
        st.caption("Uma linha por rodada, da mais antiga para a mais nova; uma única mesa. "
                   "O CSV antigo de entradas não serve como histórico completo.")
        arquivo = st.file_uploader("Histórico de todas as rodadas (CSV)", type=["csv"], key=prefixo+"_csv")
        modelo = ("id_rodada;mesa;horario;numero\n1;minha_mesa;2026-11-02T15:00:00-03:00;7\n" if jogo == "roleta" else
                  "id_rodada;mesa;horario;resultado;soma\n1;minha_mesa;2026-11-02T15:00:00-03:00;E;7\n")
        st.download_button("Baixar modelo CSV", modelo.encode("utf-8-sig"), file_name=f"modelo_{jogo}.csv",
                           mime="text/csv", key=prefixo+"_modelo")
    elif fonte == "Sessão atual":
        st.caption("Inclui apenas as rodadas novas observadas desde a abertura desta sessão; "
                   "a faixa inicial de resultados da mesa não é contada retroativamente.")
    else:
        st.caption("Dados gerados por sorteio: servem para testar o software; não comprovam vantagem numa mesa real.")
    c1, c2 = st.columns(2)
    n_sim = c1.number_input("Rodadas no controle simulado", min_value=200, max_value=200_000,
                            value=20_000, step=1000, key=prefixo+"_n")
    semente = c2.number_input("Semente do controle", min_value=0, max_value=1_000_000_000,
                              value=42, key=prefixo+"_semente")
    with st.expander("Ficha fixa, amostra e limites da observação"):
        a, b, c = st.columns(3)
        ficha = a.number_input("Ficha por alvo (R$)", min_value=0.01, value=10.0, key=prefixo+"_ficha")
        protecao = b.number_input("Proteção no zero (R$)" if jogo == "roleta" else "Proteção no empate (R$)",
                                  min_value=0.0, value=0.0, key=prefixo+"_protecao")
        minimo = c.number_input("Mínimo de sinais em cada período", min_value=30, max_value=20_000,
                                value=200, step=50, key=prefixo+"_min")
        a, b, c, d = st.columns(4)
        banca = a.number_input("Banca da observação (R$)", min_value=1.0, value=1000.0, key=prefixo+"_banca")
        exposicao = b.number_input("Exposição máxima (%)", min_value=0.1, max_value=100.0,
                                    value=2.0, key=prefixo+"_exposicao")
        stop_loss = c.number_input("Limite de perda (%)", min_value=0.1, max_value=100.0,
                                    value=10.0, key=prefixo+"_stop_loss")
        stop_gain = d.number_input("Limite de ganho (%)", min_value=0.1, max_value=100.0,
                                    value=10.0, key=prefixo+"_stop_gain")
        st.caption("Uma entrada por rodada no acompanhamento, sem progressão de ficha. "
                   "A comparação dos padrões usa ficha fixa e não aplica paradas de banca.")
    config = ConfigPesquisa(float(ficha), float(protecao), float(banca), int(minimo),
                            exposicao_maxima=float(exposicao)/100,
                            stop_loss=float(stop_loss)/100, stop_gain=float(stop_gain)/100)
    if st.button("Analisar com treino, validação e teste", type="primary", key=prefixo+"_analisar"):
        try:
            avisos = []
            if fonte == "Importar histórico CSV":
                if arquivo is None:
                    raise ValueError("Selecione o CSV completo da mesa.")
                registros, avisos = importar_historico_pesquisa(arquivo.getvalue(), jogo)
                rotulo_fonte = "historico_informado"
            elif fonte == "Sessão atual":
                with sessao.trava:
                    registros = list(motor.registros_pesquisa)
                rotulo_fonte = "sessao_capturada"
            else:
                registros = simular_pesquisa(int(n_sim), int(semente), jogo)
                rotulo_fonte = "simulado"
            barra = st.progress(0.0, text="Avaliando períodos cronológicos…")
            relatorio = analisar_pesquisa(registros, jogo, config, fonte=rotulo_fonte,
                                         ao_progredir=lambda f: barra.progress(f))
            barra.empty()
            st.session_state[prefixo+"_resultado"] = (relatorio, csv_historico_pesquisa(registros, jogo), avisos)
        except ValueError as erro:
            st.error(str(erro))
    resultado = st.session_state.get(prefixo+"_resultado")
    if resultado:
        relatorio, csv_dados, avisos = resultado
        for aviso in avisos:
            st.warning(aviso)
        st.caption(f"Resultado congelado para {relatorio['rodadas']:,} rodadas; "
                   f"mesa: {relatorio['mesa']}. Alterar controles exige executar uma nova análise.")
        if not relatorio["metadados_completos"]:
            st.caption("Faltam IDs, horários ou identificação da mesa para completar a avaliação da origem dos dados.")
        escolhido = next((r for r in relatorio["tabela"] if r["chave"] == relatorio["selecionado_no_treino"]), None)
        if relatorio["criterios_atendidos_no_historico"]:
            st.success("O candidato escolhido no treino atendeu aos critérios neste histórico informado. "
                       "Confirme em dados futuros antes de interpretar como evidência nova.")
        else:
            st.warning("A meta ainda não foi demonstrada com retorno positivo e evidência suficiente em dados reais.")
        if escolhido:
            st.write("Candidato escolhido somente no treino: **" + escolhido["nome"] + "**")
            a, b, c, d = st.columns(4)
            s = escolhido["teste"]
            a.metric("Sinais no teste final", s["entradas"])
            b.metric("Acerto no teste", formatar_pct(s["acerto"]) if s["acerto"] is not None else "—")
            c.metric("ROI no teste", formatar_pct(s["roi"]) if s["roi"] is not None else "Incompleto")
            d.metric("Queda máxima no teste", formatar_reais(s["queda_maxima"]) if s["queda_maxima"] is not None else "Incompleta")
            if escolhido["motivos"]:
                st.caption("; ".join(escolhido["motivos"]))
            if st.button("Acompanhar candidato em observação", key=prefixo+"_acompanhar"):
                padrao = next(p for p in catalogo_pesquisa(jogo) if p.chave == escolhido["chave"])
                with sessao.trava:
                    motor.acompanhamento_pesquisa = AcompanhamentoPesquisa(
                        padrao, ConfigPesquisa(**relatorio["config"]), list(motor.historico))
                st.success("Acompanhamento iniciado a partir de agora. Volte ao Monitor para acompanhar; sem apostas automáticas.")
        fase = st.radio("Período da tabela", ["teste", "validacao", "treino"],
                         format_func=lambda x: {"teste": "Teste final (25%)", "validacao": "Validação (25%)", "treino": "Treino (50%)"}[x],
                         key=prefixo+"_fase", horizontal=True)
        tabela = []
        for r in relatorio["tabela"]:
            s = r[fase]
            tabela.append({"Padrão": r["nome"], "Sinais": s["entradas"],
                           "Acerto alvo": formatar_pct(s["acerto"]) if s["acerto"] is not None else "—",
                           "IC 95%": " a ".join(formatar_pct(v) for v in s["wilson_95"]),
                           "Limite inferior corrigido": formatar_pct(s["wilson_corrigido"][0]),
                           "Acerto inferior conservador": formatar_pct(s["acerto_limite_conservador"]),
                           "Referência teórica": formatar_pct(r["matematica"]["chance_alvo"]),
                           "Lucro": formatar_reais(s["lucro"]) if s["lucro"] is not None else "Incompleto",
                           "ROI": formatar_pct(s["roi"]) if s["roi"] is not None else "—",
                           "ROI inferior conservador": formatar_pct(s["roi_limite_inferior"]) if s["roi_limite_inferior"] is not None else "—",
                           "Empates sem pagamento": s["liquidacoes_incompletas"]})
        st.dataframe(tabela, hide_index=True, use_container_width=True)
        if relatorio["curva_teste"] and escolhido:
            st.markdown(Html.grafico_curva([(i, lucro, 0.0) for i, lucro in relatorio["curva_teste"]],
                                           "Resultado do candidato no teste final", "rodadas", "Referência zero"),
                        unsafe_allow_html=True)
        a, b = st.columns(2)
        a.download_button("Baixar relatório completo JSON", json.dumps(relatorio, ensure_ascii=False, indent=2).encode("utf-8"),
                           file_name=f"validacao_{jogo}.json", mime="application/json", key=prefixo+"_json")
        b.download_button("Baixar histórico usado no teste", csv_dados,
                           file_name=f"historico_{jogo}.csv", mime="text/csv", key=prefixo+"_hist_testado")
    with sessao.trava:
        registros_atuais = list(motor.registros_pesquisa)
    st.download_button("Exportar todas as rodadas da sessão atual", csv_historico_pesquisa(registros_atuais, jogo),
                       file_name=f"historico_completo_{jogo}.csv", mime="text/csv", key=prefixo+"_hist_sessao")
    with st.expander("Como interpretar os resultados e fontes"):
        st.write("Acerto conta somente o alvo principal; proteção, empate, gale e várias apostas não inflam essa taxa. "
                 "Duas dúzias/colunas cobrem 24/37 casas (64,86%), mas precisam de 66,67% de acerto para empatar sem proteção. "
                 "Cada lado do Bac Bo vence em 575/1296 combinações (44,37%).")
        st.write("A seleção usa apenas o treino e permanece congelada. O teste final não escolhe o vencedor. "
                 "Wilson e a correção de Bonferroni medem incerteza; o limite inferior conservador do ROI usa a faixa exata "
                 "de pagamentos e a desigualdade de Hoeffding. Esses cálculos pressupõem rodadas independentes. "
                 "Repetir a análise até aparecer um resultado bom invalida a interpretação de teste reservado.")
        for nome, url in FONTES_PESQUISA.items():
            st.markdown(f"[{nome}]({url})")


def rodar_pesquisa_terminal(args) -> None:
    config = ConfigPesquisa(valor_por_alvo=args.ficha_pesquisa, protecao=args.protecao_pesquisa,
                            banca_inicial=args.banca_pesquisa, minimo_sinais=args.min_sinais_pesquisa)
    if args.pesquisa and args.pesquisa_simulada is not None:
        raise ValueError("Escolha --pesquisa ou --pesquisa-simulada.")
    if args.pesquisa:
        with open(args.pesquisa, "rb") as arquivo:
            registros, avisos = importar_historico_pesquisa(arquivo.read(), args.jogo)
        fonte = "historico_informado"
    else:
        registros, avisos = simular_pesquisa(args.pesquisa_simulada, args.semente if args.semente is not None else 42, args.jogo), []
        fonte = "simulado"
    relatorio = analisar_pesquisa(registros, args.jogo, config, fonte=fonte)
    destino = args.relatorio_pesquisa or f"validacao_{args.jogo}.json"
    with open(destino, "w", encoding="utf-8") as arquivo:
        json.dump(relatorio, arquivo, ensure_ascii=False, indent=2)
    for aviso in avisos:
        exibir("Aviso: " + aviso)
    exibir(f"Pesquisa {args.jogo}: {len(registros)} rodadas | relatório: {destino}")
    exibir("Candidato escolhido no treino: " + str(relatorio["selecionado_no_treino"]))
    exibir("Critérios atendidos neste histórico: " + ("SIM" if relatorio["criterios_atendidos_no_historico"] else "NÃO"))
    exibir("Não há garantia de acerto ou lucro futuro. Simulação não comprova vantagem em mesa real.")


def salvar_foto_pesquisa(motor) -> None:
    primeiro = motor.registros_pesquisa[0] if len(motor.registros_pesquisa) == LIMITE_REGISTROS_PESQUISA else None
    motor._foto_pesquisa = (primeiro, motor.descartados_pesquisa, copy.deepcopy(motor.acompanhamento_pesquisa))


def desfazer_registro_pesquisa(motor) -> None:
    foto = getattr(motor, "_foto_pesquisa", None)
    if foto is not None:
        primeiro, motor.descartados_pesquisa, motor.acompanhamento_pesquisa = foto
        if motor.registrar and motor.registros_pesquisa:
            motor.registros_pesquisa.pop()
            if primeiro is not None:
                motor.registros_pesquisa.appendleft(primeiro)
        motor._foto_pesquisa = None


if __name__ == "__main__":
    if rodando_no_streamlit():
        app_web()  # streamlit run robo_roleta.py
    else:
        try:
            main()  # python robo_roleta.py
        except KeyboardInterrupt:
            exibir("\nEncerrado.")
