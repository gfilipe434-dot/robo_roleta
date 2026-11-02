# Robô de análise — Roleta e Bac Bo

Visual 2.1 · Núcleo de pesquisa 2.0 · 02/11/2026

O arquivo `robo_roleta.py` está completo e pode substituir o arquivo anterior. A interface e os três padrões originais da roleta, os seis do Bac Bo, os modos manual/automático e os testes de aceitação foram preservados. A nova área **Pesquisa e validação** avalia 19 hipóteses de roleta e 15 de Bac Bo, incluindo 25 hipóteses adicionais em relação aos padrões originais.

**A meta de acerto superior a 60% não foi demonstrada em uma mesa real.** Não foi fornecido um histórico real completo nesta solicitação. As novas regras são hipóteses para avaliação e acompanhamento em observação; não são estratégias de lucro comprovado. Nenhuma aposta é enviada pelo programa.


## Atualização visual realista

O lobby recebeu uma roleta com 37 casas numeradas na ordem europeia, madeira escura, aro metálico, esfera em órbita e feltro texturizado. O Bac Bo mostra os quatro dados em 3D, com posições diferentes, bases metálicas e cúpulas transparentes. Esses elementos são ilustrativos; os resultados efetivos continuam no monitor da sessão.

O novo tema combina verde escuro, marfim e dourado. Os cartões, indicadores, botões e fundos do painel acompanham essa identidade. O menu inicia recolhido em telas pequenas; em tablets, as mesas ficam uma abaixo da outra. As animações respeitam a preferência de reduzir movimento do dispositivo.

As cenas são geradas pelo próprio arquivo em CSS e SVG, sem arquivos de imagem, fontes externas ou serviços gráficos. Para aplicar a atualização, encerre o processo anterior, substitua o arquivo completo e abra o painel novamente. Os instaladores e o modo de abertura continuam os mesmos.

## Instalar e abrir

Recomendado: Python 3.10 ou mais recente e Google Chrome para a leitura automática. No computador, instale com `requirements-pc.txt` (inclui o Playwright da leitura automática); o `requirements.txt` é o do site hospedado, que não lê mesas. O núcleo de análise usa a biblioteca padrão do Python. O painel foi testado com Python 3.12 e Streamlit 1.66.1.

1. Extraia o ZIP em uma pasta.
2. No Windows, execute `INSTALAR.bat` uma vez.
3. Execute `ABRIR_ROBO.bat` para abrir o painel. O lançador existente inicia o servidor em segundo plano.

Alternativamente:

```bash
python -m pip install -r requirements-pc.txt
python robo_roleta.py --web
```

Para abrir diretamente com Streamlit:

```bash
python -m streamlit run robo_roleta.py
```

A leitura automática do Chrome original foi preservada. Ela continua dependendo da mesa, do navegador e da calibração da faixa de resultados. Não foi testada em uma conta de cassino nesta entrega. A aplicação não inclui conta, senha, assinatura de dados ou uma API de resultados contratada.

Ao substituir o arquivo em uma instalação anterior, mantenha os arquivos de configuração e o perfil do navegador na pasta original. O processo do painel precisa ser reiniciado para carregar o código novo. O botão antigo de atualização remota busca a versão do repositório configurado no próprio código; essa versão remota pode ser diferente desta entrega.

## Usar a nova análise

1. Entre na **Roleta** ou no **Bac Bo**.
2. Na barra lateral, escolha **Área → Pesquisa e validação**.
3. Escolha **Importar histórico CSV**, **Sessão atual** ou **Simulação de controle**.
4. Ajuste ficha, proteção, mínimo de sinais e limites. A proteção começa em zero na nova pesquisa; os padrões antigos mantêm suas configurações anteriores.
5. Clique em **Analisar com treino, validação e teste**.
6. Consulte os três períodos e baixe o relatório JSON e o histórico utilizado.
7. Se houver candidato escolhido no treino, **Acompanhar candidato em observação** inicia uma conta separada para acompanhar apenas as próximas rodadas. Volte ao **Monitor** para ver esse acompanhamento.

O candidato pode ser acompanhado mesmo quando não atende à meta: o painel mantém a indicação de observação. Esse botão não certifica a estratégia nem transforma simulação em evidência real.

## O que foi acrescentado

- Roleta: repetição com reversão ou continuação, alternância com continuação ou quebra, cobertura de duas dúzias/colunas, continuação em uma dúzia/coluna, paridade e faixa 1–18/19–36.
- Bac Bo: reversão/continuação em diferentes tamanhos de sequência, alternâncias de quatro/seis resultados, duplas, triplas, repetição de empate e retomada do lado anterior ao empate.
- Registro de todas as novas rodadas observadas no painel, inclusive sem sinal. O limite é de 200.000 rodadas por sessão; o painel informa quando registros antigos saem desse limite.
- Importação com validação de números, somas, ordem temporal, mesa única e IDs conflitantes. Resultados consecutivos iguais são preservados.
- Treino, validação e teste em ordem cronológica; candidato congelado antes de consultar os períodos posteriores.
- Acerto do alvo principal, intervalo de Wilson, limites conservadores de acerto/ROI, retorno líquido, queda máxima desde o pico e sequência de perdas.
- Comparação matemática por enumeração das 37 casas ou das 1.296 combinações dos quatro dados.
- Uma entrada por rodada no acompanhamento, ficha fixa, controle da exposição total, saldo, limite de perda e limite de ganho. Não há martingale ou recuperação automática de perdas.
- Desfazer restaura também o registro completo e a conta do acompanhamento.

Os valores antigos de banca continuam sendo o comparativo das estratégias originais. A nova conta de observação aparece separadamente. Seus limites não alteram os cálculos dos backtests antigos.

## Formato dos históricos

Uma linha por rodada, da mais antiga para a mais nova. Use uma única mesa por arquivo. Separadores aceitos: ponto e vírgula, vírgula ou tabulação. UTF-8 com ou sem BOM e CP1252 são aceitos.

Roleta:

```csv
id_rodada;mesa;horario;numero
1;minha_mesa;2026-11-02T15:00:00-03:00;7
2;minha_mesa;2026-11-02T15:00:40-03:00;7
3;minha_mesa;2026-11-02T15:01:20-03:00;0
```

Bac Bo:

```csv
id_rodada;mesa;horario;resultado;soma
1;minha_mesa;2026-11-02T15:00:00-03:00;P;9
2;minha_mesa;2026-11-02T15:00:40-03:00;B;8
3;minha_mesa;2026-11-02T15:01:20-03:00;E;7
```

`resultado` aceita P/PLAYER, B/BANKER e E/EMPATE/T/TIE. A soma é a soma vencedora, ou a soma dos dois lados no empate. A soma vencedora 2 só é possível em empate. Não se trata do bacará com cartas.

A coluna `numero` ou `resultado` é obrigatória. IDs, mesa e horários completos são necessários para a indicação de critérios atendidos no histórico. O programa aceita dados sem esses metadados para exploração, mas assume a ordem das linhas e não comprova a origem. Datas sem fuso são interpretadas como UTC−3.

O exportador da sessão usa **IDs e horários locais de captura**, não IDs/horários autenticados do provedor. A faixa histórica inicial da mesa não é registrada como se tivesse sido observada ao vivo. O arquivo antigo **Salvar sessão** contém apenas entradas; ele não é um histórico completo e é rejeitado para esta análise.

No Bac Bo, um empate sem soma tem pagamento variável desconhecido. Com proteção ou alvo Empate, a pesquisa marca a liquidação como incompleta e não fornece lucro/ROI/queda como exatos. A conta de observação é pausada. Sem proteção, uma aposta em P/B perde 10% no empate, e esse valor é conhecido mesmo sem a soma. O comparativo antigo mantém sua regra de pagamento mínimo para preservar a compatibilidade, mas agora exibe um aviso de saldo estimado nesses casos.

Os registros completos ficam na sessão em memória. Exporte o CSV antes de encerrar o processo ou iniciar nova sessão. A origem de cada registro é preservada; registros simulados não podem comprovar uma vantagem real.

## Validação estatística

- Primeiros 50% das rodadas: treino. O candidato é escolhido pelo maior limite inferior do retorno no treino, com pelo menos metade do mínimo de sinais configurado e nunca menos de 30.
- Próximos 25%: validação. Últimos 25%: teste final. Os sinais são sempre apurados na rodada seguinte à detecção, inclusive nas fronteiras entre períodos.
- Padrão fixo de 200 sinais mínimos em **cada** período posterior. O limite não é uma garantia de amostra suficiente para qualquer efeito; um candidato raro pode continuar sem evidência.
- A meta exige limites inferiores de acerto acima de 60% e da referência teórica, retorno inferior conservador positivo, liquidações completas e metadados de origem completos nos períodos de validação e teste.
- O orçamento de erro de 5% é dividido entre padrões, três períodos, dois indicadores e todos os tamanhos de amostra possíveis até o horizonte do arquivo. Wilson é aproximado; há também um limite conservador de acerto. As hipóteses, fórmulas e limites estão em `FONTES_E_METODOLOGIA.md`.
- Cada linha da tabela é uma comparação contrafactual de um padrão sozinho, sem paradas de banca. Não some as linhas como se fossem uma única carteira de apostas.
- Reexecutar após consultar o teste, mudar regras ou experimentar outros arquivos até aparecer lucro exige um novo período futuro reservado. A correção não cobre toda essa busca acumulada.

## Comandos de pesquisa

```bash
python robo_roleta.py --pesquisa historico_roleta.csv --jogo roleta --relatorio-pesquisa validacao_roleta.json
python robo_roleta.py --pesquisa historico_bacbo.csv --jogo bacbo --protecao-pesquisa 1 --relatorio-pesquisa validacao_bacbo.json
python robo_roleta.py --pesquisa-simulada 200000 --jogo roleta --semente 42 --relatorio-pesquisa controle_roleta.json
python robo_roleta.py --pesquisa-simulada 200000 --jogo bacbo --semente 42 --relatorio-pesquisa controle_bacbo.json
```

Valores opcionais: `--ficha-pesquisa`, `--protecao-pesquisa`, `--banca-pesquisa` e `--min-sinais-pesquisa`.

## Testes e arquivos de controle

```bash
python -m pip install -r tests/requirements.txt
python -m pytest tests -q
```

Os controles incluídos (pasta `controles/`) usam dados simulados, 200.000 rodadas por jogo, semente 42 e ficha fixa sem proteção. Eles servem para inspecionar o funcionamento e a ausência de vantagem demonstrada, sem representar uma mesa real.

Os backtests originais de 1.000.000 de rodadas com semente 42 foram conferidos:

| Jogo | Entradas | Total apostado | Resultado |
|---|---:|---:|---:|
| Roleta | 195.368 | R$ 3.527.208,00 | −R$ 90.804,00 |
| Bac Bo | 515.257 | R$ 5.554.907,00 | −R$ 105.951,00 |

Consulte `VALIDACAO_ENTREGA.json` para as verificações desta versão. Esses resultados confirmam a reprodução do motor antigo, não uma previsão de rentabilidade.
