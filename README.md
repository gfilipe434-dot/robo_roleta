# Sinais de roleta funcionam?

Robô em Python que lê uma roleta europeia ao vivo, aplica três padrões populares de "sinais" e confere cada entrada sozinho numa banca fictícia. Os mesmos padrões foram testados em 1 milhão de giros simulados.

**Resposta curta: não.** Os padrões acertam na mesma taxa de um giro qualquer, e a banca termina onde a matemática da roleta prevê.

> **Demo online:** _cole aqui o link do seu app no Streamlit_
>
> O robô só observa. Nenhuma aposta é feita: todos os valores são de uma banca fictícia.

## Os três padrões testados

| Padrão | Gatilho | Entrada sugerida | Chance real do alvo | Acerto para empatar |
|---|---|---|---|---|
| Cor | 4 números da mesma cor seguidos | a cor oposta | 48,6% | 50,0% |
| Dúzia | 3 números seguidos na mesma dúzia | as outras duas dúzias | 64,9% | 66,7% |
| Coluna | 3 números seguidos na mesma coluna | as outras duas colunas | 64,9% | 66,7% |

## Resultado do backtest (1.000.000 de giros, semente 42)

| Padrão | Sinais | Acerto | Chance real | Resultado |
|---|---|---|---|---|
| Cor | 57.552 | 48,7% | 48,6% | −R$ 16.452 |
| Dúzia | 68.907 | 64,9% | 64,9% | −R$ 38.361 |
| Coluna | 68.909 | 65,1% | 64,9% | −R$ 35.991 |
| **Total** | **195.368** | | | **−R$ 90.804** (−2,57% do apostado) |

A vantagem da casa na roleta europeia é 1/37 = 2,70%. O resultado real ficou dentro do previsto pela matemática.

## Funcionalidades

- **Painel visual (Streamlit):** últimas pedras com as cores da mesa, alerta de entrada, desempenho por padrão e gráfico da banca contra a curva esperada.
- **4 modos:** leitura automática da mesa ao vivo (Playwright, só no computador), entrada manual com tabuleiro clicável, simulador ao vivo e backtest em massa.
- **Leitura ao vivo robusta:** acha a faixa de resultados pelo atributo `data-role="number-N"` (inclusive em iframes aninhados e shadow DOM), confirma cada mudança com duas leituras, recupera giros perdidos e reencontra a faixa se a página recarregar.
- **Modo terminal completo**, com menu, para quem prefere rodar sem navegador.
- **Testes de aceitação reproduzíveis:** `--backtest 1000000 --semente 42` sempre dá 195.368 sinais e −R$ 90.804,00.

## Arquitetura

```
Coletor (simulador | manual | navegador | API)
        │  próximo número
        ▼
MonitorRoleta / MotorWeb ──► BancaFicticia      (liquida os sinais do giro anterior)
        │                ──► EstrategiaRoleta   (procura novos sinais)
        │                ──► Painel / tela      (mostra tudo)
        └─ histórico: deque(maxlen=20)
```

## Como rodar no computador

```bash
pip install streamlit              # painel visual
pip install playwright             # só para a leitura automática da mesa

python robo_roleta.py              # menu com todos os modos (terminal)
python robo_roleta.py --web        # painel visual no navegador, rodando escondido
streamlit run robo_roleta.py       # painel visual (forma direta)
python robo_roleta.py --backtest 1000000 --semente 42   # teste de aceitação
```

## Tecnologias

Python 3.9+ · Programação orientada a objetos (ABC, dataclasses) · Streamlit · Playwright e Chrome DevTools Protocol · JavaScript (DOM) · Estatística (intervalo de confiança de 95%)

---

Projeto de **Filipe Misael**, 2026.
