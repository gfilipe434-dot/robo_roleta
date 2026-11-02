# Fontes e metodologia

Pesquisa consultada em 02/11/2026. As regras financeiras consideradas são as da roleta europeia comum sem la partage/en prison e do Bac Bo tradicional, com a tabela de pagamentos descrita abaixo. Variantes com multiplicadores ou pagamentos diferentes exigem outro modelo de liquidação.

## Fontes externas primárias

1. [Evolution — Bac Bo](https://games.evolution.com/live-casino/live-craps-and-dice/bac-bo/): o fabricante descreve quatro dados, duas somas e vitória da maior soma; empates têm pagamentos variáveis. Não publica nessa página uma estratégia de sequências com 60% de acerto.
2. [Cloudbet — regras e pagamentos do Bac Bo oferecido pelo operador](https://www.cloudbet.com/pt-br/casino/play/evolution/ev_bac_bo): fonte operacional para pagamentos de empate de 88:1, 25:1, 10:1, 6:1 e 4:1, conforme a soma, e devolução de 90% em Player/Banker no empate. Essa referência é usada para as regras, não como indicação de operador.
3. [NIST — intervalo de Wilson](https://www.itl.nist.gov/div898/handbook/prc/section2/prc241.htm): base para o intervalo aproximado da proporção de acertos.
4. [NIST — método de Bonferroni](https://www.itl.nist.gov/div898/handbook/prc/section4/prc473.htm): base para repartir o orçamento de erro entre várias comparações. A aplicação ao catálogo, períodos e horizontes deste software é uma escolha desta implementação.
5. [Hoeffding, 1963 — Probability Inequalities for Sums of Bounded Random Variables](https://www.tandfonline.com/doi/abs/10.1080/01621459.1963.10500830): artigo original sobre concentração para somas de variáveis limitadas e independentes.
6. [Gambling Commission — retorno e vantagem da casa](https://www.gamblingcommission.gov.uk/public-and-players/guide/return-to-player-how-much-gaming-machines-payout/): distingue retorno médio de resultado por sessão e descreve a vantagem matemática do cassino.

Nenhuma dessas fontes valida as sequências adicionadas como previsões rentáveis. Repetição, alternância, duplas e triplas são hipóteses explícitas do catálogo, testadas pelo programa. Não foram apresentadas como achados comprovados de pesquisa externa. Publicações promocionais que prometem “assertividade garantida” não foram usadas como fundamento técnico.

## Probabilidades calculadas no próprio código

A enumeração das 37 casas equiprováveis encontra 18/37 = 48,6486% para uma cor, paridade ou metade. Duas dúzias/colunas cobrem 24/37 = 64,8649%. Sem proteção, duas fichas em duas dúzias produzem lucro de uma ficha no acerto e perda de duas fichas no erro: o equilíbrio requer 2/3 = 66,6667%. Assim, superar 60% não implica lucro.

Com quatro dados comuns e independentes, há 6^4 = 1.296 combinações. Player e Banker vencem em 575 combinações cada; 146 são empates. Cada lado tem 44,3673% de chance de vencer por rodada. Excluir empates muda o denominador para 50%, mas não aumenta a chance absoluta de vitória; o programa mantém todos os sinais no denominador.

Os retornos esperados são calculados enumerando cada resultado com os pagamentos e a proteção configurados. Na roleta, a margem esperada é −1/37 do total apostado. No Bac Bo, sem proteção, o retorno esperado é −14,6/1296 no lado e −58/1296 no empate. As porcentagens vêm da enumeração e das regras citadas, não de uma previsão de IA.

## Medidas e critérios

O acerto conta somente a ocorrência do alvo principal. Uma proteção lucrativa não se transforma em acerto do alvo. ROI = lucro líquido / exposição total. A exposição inclui cada alvo e a proteção. A queda máxima considera a distância entre o lucro acumulado e seu maior pico anterior.

Para p = acertos/n, o intervalo de Wilson usa o quantil normal correspondente ao alpha escolhido. O intervalo normal de 95% é mostrado como diagnóstico aproximado. O intervalo corrigido usa alpha ajustado. A aprovação histórica exige também um limite conservador de acerto, evitando depender somente da aproximação de Wilson.

Se K é a quantidade fixa de padrões e N a quantidade de rodadas do arquivo, alpha_individual = 0,05 / (K × 3 × 2 × N). Os fatores cobrem os padrões, os três períodos, os dois indicadores e os possíveis tamanhos de amostra até o horizonte. É uma escolha conservadora, para que o número aleatório de gatilhos não seja tratado simplesmente como tamanho fixado antes.

Para retornos normalizados com limites a e b obtidos por enumeração, o limite inferior utilizado é:

`ROI_inferior = ROI_observado − (b−a) × sqrt(ln(1/alpha_individual)/(2n))`.

Para o acerto, usa-se adicionalmente:

`acerto_inferior = max(0, acerto_observado − sqrt(ln(1/alpha_individual)/(2n)))`.

As contas pressupõem rodadas independentes e regras de liquidação estáveis. Se houver dependência, mudança de mecanismo, lacunas sistemáticas, erro de captura ou seleção de dados, a interpretação estatística pode falhar. Os intervalos não autenticam o provedor nem provam uma probabilidade futura constante.

O candidato é escolhido no treino e congelado. Para sinalizar critérios atendidos no histórico informado, os períodos de validação e teste precisam, separadamente, superar a meta de 60% e a referência teórica nos limites inferiores, apresentar ROI inferior positivo e atingir o mínimo de sinais. Dados simulados, origem desconhecida, metadados incompletos ou pagamentos incompletos bloqueiam essa indicação.

O gráfico final e a tabela são retrospectivos. A indicação de critérios atendidos se refere somente ao histórico enviado. Ela não certifica uma estratégia de cassino, não garante retorno futuro e não pode ser transportada automaticamente para outra mesa, outro período ou outra tabela de pagamentos.
