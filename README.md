# Sinais de roleta e Bac Bo funcionam?

Robô em Python que acompanha uma roleta europeia e uma mesa de Bac Bo, aplica padrões populares de "sinais" e confere cada entrada sozinho numa banca fictícia. Os mesmos padrões foram testados em 1 milhão de rodadas simuladas de cada jogo.

**Resposta curta: não.** Os padrões acertam na mesma taxa de uma rodada qualquer, e a banca termina onde a matemática de cada jogo prevê.

> **Demo online:** https://robo-roleta-filipe.streamlit.app
>
> O robô só observa. Nenhuma aposta é feita: todos os valores são de uma banca fictícia.

## Roleta

### Os três padrões testados

| Padrão | Gatilho | Entrada sugerida | Chance real do alvo | Acerto para empatar |
|---|---|---|---|---|
| Cor | 4 números da mesma cor seguidos | a cor oposta | 48,6% | 50,0% |
| Dúzia | 3 números seguidos na mesma dúzia | as outras duas dúzias | 64,9% | 66,7% |
| Coluna | 3 números seguidos na mesma coluna | as outras duas colunas | 64,9% | 66,7% |

### Resultado do backtest (1.000.000 de giros, semente 42)

| Padrão | Sinais | Acerto | Chance real | Resultado |
|---|---|---|---|---|
| Cor | 57.552 | 48,7% | 48,6% | −R$ 16.452 |
| Dúzia | 68.907 | 64,9% | 64,9% | −R$ 38.361 |
| Coluna | 68.909 | 65,1% | 64,9% | −R$ 35.991 |
| **Total** | **195.368** | | | **−R$ 90.804** (−2,57% do apostado) |

A vantagem da casa na roleta europeia é 1/37 = 2,70%. O resultado real ficou dentro do previsto pela matemática.

## Bac Bo

Cada lado (Player e Banker) joga dois dados e ganha a maior soma. Player e Banker ganham em 575 das 1.296 combinações de dados (44,37% cada) e o empate em 146 (11,27%). Player e Banker pagam 1:1 e devolvem 90% da entrada no empate; o empate paga de 4:1 a 88:1, conforme a soma.

### Os seis padrões prontos

| Padrão | Gatilho | Entrada sugerida | Chance real do alvo | Acerto para empatar |
|---|---|---|---|---|
| 3 iguais → lado oposto | 3 Player (ou Banker) seguidos | o outro lado | 44,4% | 44,9% |
| Alternância → continua | P B P B | continua alternando | 44,4% | 44,9% |
| 2 iguais → repete | 2 iguais seguidos | o mesmo lado | 44,4% | 44,9% |
| Empate → empate | saiu empate | empate | 11,3% | 11,8% |
| Duplas → volta o primeiro | P P B B | o primeiro lado | 44,4% | 44,9% |
| 4 iguais → surfa | 4 iguais seguidos | o mesmo lado | 44,4% | 44,9% |

Além desses, o painel aceita **padrões cadastrados por você**, um por linha (`PPB -> P`, `BBBB -> P`, `EP -> E`), sem mexer no código.

### Resultado do backtest (1.000.000 de rodadas, semente 42)

Cada padrão como se entrasse sozinho:

| Padrão | Sinais | Acerto | Chance real | Resultado |
|---|---|---|---|---|
| 3 iguais → lado oposto | 97.190 | 44,3% | 44,4% | −R$ 13.475 |
| Alternância → continua | 43.146 | 44,2% | 44,4% | −R$ 9.497 |
| 2 iguais → repete | 218.961 | 44,4% | 44,4% | −R$ 32.828 |
| Empate → empate | 112.920 | 11,4% | 11,3% | −R$ 37.040 |
| Duplas → volta o primeiro | 77.262 | 44,3% | 44,4% | −R$ 11.931 |
| 4 iguais → surfa | 43.040 | 44,4% | 44,4% | −R$ 8.951 |

Na banca, o robô dá **uma entrada por rodada**: padrões que apontam o mesmo alvo viram uma entrada só e, quando discordam (ex.: P P B B dispara "2 iguais" → Banker e "Duplas" → Player), vale o padrão mais longo. Foram **515.257 entradas** e a banca terminou em **−R$ 105.951** (−1,91% do apostado), com entradas de R$ 10 e R$ 1 de proteção no empate. A vantagem da casa no Bac Bo é 1,13% em Player/Banker e 4,48% no empate; a matemática previa −R$ 113.866, e o resultado ficou dentro da variação normal.

## Versão 2.0: pesquisa e validação

A área **Pesquisa e validação** testa 19 hipóteses de roleta e 15 de Bac Bo (além dos padrões originais) com rigor estatístico: os dados são divididos em ordem cronológica em treino (50%), validação (25%) e teste final (25%), o candidato é escolhido só no treino e congelado, e cada período mostra acerto, intervalo de Wilson com correção de Bonferroni, limite conservador de retorno (Hoeffding), queda máxima e sequência de perdas. Aceita o histórico completo da mesa em CSV, as rodadas da sessão atual ou uma simulação de controle.

Nos controles simulados de 200.000 rodadas, nenhum candidato atingiu a meta: o melhor da roleta acertou 65,5% (precisava de 66,7% só para empatar) e o do Bac Bo, 43,9%, ambos com retorno negativo no teste final. Detalhes em `LEIA-ME.md` e `FONTES_E_METODOLOGIA.md`.

O visual também mudou: lobby com roleta numerada em SVG e quatro dados 3D sob cúpulas, tema verde, marfim e dourado, tudo gerado no próprio arquivo, sem imagens nem fontes externas.

## Funcionalidades

- **Painel visual (Streamlit):** últimas pedras com as cores da mesa, alerta de entrada, desempenho por padrão e gráfico da banca contra a curva esperada.
- **Lobby 3D:** a primeira tela é a escolha da mesa, com uma roleta girando e dois dados rolando, feitos só com CSS 3D (sem bibliotecas).
- **Som dos sinais:** toca um aviso quando sai um gatilho (e, se quiser, no GREEN e no LOSS), gerado com a Web Audio API do navegador, sem arquivos de áudio e sem repetir o mesmo sinal.
- **Dois jogos no mesmo painel:** roleta europeia e Bac Bo, com sessões separadas (trocar de jogo não apaga nada).
- **4 modos:** leitura automática da mesa ao vivo (Playwright, só no computador), entrada manual com tabuleiro clicável, simulador ao vivo e backtest em massa.
- **Leitura ao vivo do Bac Bo:** lê o quadro de bolinhas da mesa pelo `data-type="roadItemColor"` do SVG, ordena pela posição na tela (coluna por coluna) e entende quando o quadro enche e a coluna mais antiga sai.
- **Padrões do Bac Bo configuráveis:** liga e desliga os prontos e cadastra os seus em texto simples; ficam salvos no computador.
- **Uma entrada por rodada:** sinais no mesmo alvo se juntam; sinais que discordam seguem a regra escolhida (vale o mais longo, ou não entra).
- **No computador, painel enxuto:** só o jogo, a banca, o valor da entrada e o da proteção (com sugestão de 1% da banca por alvo) e o botão **Salvar sessão** baixa a planilha das entradas.
- **Leitura ao vivo robusta:** acha a faixa de resultados pelo atributo `data-role="number-N"` (inclusive em iframes aninhados e shadow DOM), confirma cada mudança com duas leituras, recupera giros perdidos e reencontra a faixa se a página recarregar.
- **Modo terminal completo**, com menu, para quem prefere rodar sem navegador.
- **Testes de aceitação reproduzíveis:** `--backtest 1000000 --semente 42` sempre dá 195.368 sinais e −R$ 90.804,00 na roleta; `--jogo bacbo --backtest 1000000 --semente 42` sempre dá 515.257 entradas e −R$ 105.951,00 no Bac Bo.

## Arquitetura

```
Coletor (simulador | manual | navegador | API)
        │  próximo número
        ▼
MonitorRoleta / MotorWeb ──► BancaFicticia      (liquida os sinais do giro anterior)
        │                ──► EstrategiaRoleta   (procura novos sinais)
        │                ──► Painel / tela      (mostra tudo)
        └─ histórico: deque(maxlen=20)

Bac Bo: RodadaBacBo ──► MotorBacBo ──► BancaBacBo (pagamentos reais do Bac Bo)
                                   └─► EstrategiaBacBo (padrões prontos + os seus)
```

## Como rodar no computador

```bash
pip install streamlit              # painel visual
pip install playwright             # só para a leitura automática da mesa (ou: pip install -r requirements-pc.txt)

python robo_roleta.py              # menu com todos os modos (terminal)
python robo_roleta.py --web        # painel visual no navegador, rodando escondido
streamlit run robo_roleta.py       # painel visual (forma direta)
python robo_roleta.py --backtest 1000000 --semente 42   # teste de aceitação
python robo_roleta.py --jogo bacbo --backtest 1000000 --semente 42   # teste do Bac Bo
```

## Tecnologias

Python 3.9+ · Programação orientada a objetos (ABC, dataclasses) · Streamlit · Playwright e Chrome DevTools Protocol · JavaScript (DOM) · Estatística (intervalo de confiança de 95%)

---

Projeto de **Filipe Misael**, 2026.
