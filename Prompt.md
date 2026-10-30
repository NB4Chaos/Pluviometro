# REVISÃO TÉCNICA COMPLETA E EVOLUÇÃO DO SISTEMA DE CALIBRAÇÃO — PLUVIÔMETRO E MEDIDOR DE VAZÃO

Quero que você faça uma revisão profunda do projeto atual, tanto da arquitetura de software quanto da interface visual, aquisição de dados, comunicação com o datalogger e lógica metrológica.

Não quero apenas alterações pontuais. Preciso que você compreenda integralmente o funcionamento do sistema antes de modificar qualquer coisa.

O projeto é utilizado em um laboratório de metrologia da Elus Instrumentação e está conectado a um datalogger Campbell Scientific CR1000Xe. Portanto, estamos trabalhando com um sistema físico real, utilizado para ensaios e calibrações. A confiabilidade dos dados é prioridade absoluta.

**IMPORTANTE: não comece alterando arquivos imediatamente. Primeiro faça uma investigação completa da arquitetura atual, identifique os componentes envolvidos e apresente um diagnóstico técnico. Depois, implemente as melhorias com testes.**

---

# 1. IDENTIDADE VISUAL — RETORNAR À APARÊNCIA ANTERIOR

Na arquitetura atual revisada, as fontes, tipografias e alguns elementos visuais foram modificados.

Não gostei do resultado.

Quero que você retorne ao padrão visual da versão anterior do sistema, principalmente:

- Tipografia original.
- Família de fontes.
- Pesos tipográficos.
- Tamanhos e hierarquia dos textos.
- Aparência dos títulos.
- Aparência dos cards.
- Espaçamentos.
- Bordas e arredondamentos.
- Cores e identidade visual da Elus.
- Aparência dos botões e campos de configuração.

Não quero uma nova identidade visual. Quero recuperar a identidade que já tínhamos desenvolvido anteriormente.

Antes de fazer isso:

1. Verifique o histórico do projeto, caso exista Git.
2. Compare os arquivos CSS, HTML e JavaScript atuais com as versões anteriores disponíveis.
3. Procure referências visuais, imagens, arquivos de configuração e versões anteriores dentro da pasta do projeto.
4. Identifique exatamente quais alterações provocaram a mudança de tipografia.
5. Restaure o padrão anterior sem desfazer as melhorias funcionais que já foram implementadas.

**Não tente imitar a interface anterior por aproximação se houver arquivos ou histórico que permitam recuperá-la corretamente.**

# DIRETÓRIOS OFICIAIS DO TRABALHO

Existem três diretórios importantes. Utilize exatamente os caminhos abaixo:

## 1. Projeto atual — LOCAL DE TRABALHO

`C:\Users\PC\OneDrive\Documentos\Pluviometro`

Este é o diretório principal do projeto atual.

**Todas as alterações e implementações devem ser realizadas nesta pasta.**

Antes de modificar qualquer arquivo:

- Examine a estrutura completa.
- Identifique o ponto de entrada da aplicação.
- Localize os arquivos Python, CRBasic, HTML, CSS, JavaScript e JSON.
- Identifique os arquivos de configuração e banco de dados.
- Verifique se existem arquivos de versões anteriores.
- Preserve os dados e configurações existentes.

Não trabalhe diretamente no backup.

## 2. Backup antigo — REFERÊNCIA VISUAL E TIPOGRÁFICA

`C:\Users\PC\OneDrive\Documentos\Pluviometro\backup\monitor-pluviometro_simplificado\monitor-pluviometro`

Esta pasta contém a versão anterior do sistema.

**Utilize este diretório como referência para recuperar o HTML, a identidade visual e as fontes originais.**

Quero que você examine especialmente:

- Arquivos HTML.
- Arquivos CSS.
- Arquivos JavaScript relacionados à interface.
- Fontes locais.
- Importações de fontes externas.
- Variáveis CSS.
- Paleta de cores.
- Tipografia.
- Componentes visuais.
- Estrutura dos cards.
- Botões e campos.
- Espaçamentos e dimensões.

Compare esses arquivos com a versão atual do projeto.

O objetivo é recuperar a aparência anterior sem perder as funcionalidades que foram desenvolvidas posteriormente.

**ATENÇÃO:** essa pasta é somente uma referência. Não execute alterações nela e não a utilize como diretório principal de desenvolvimento.

Não copie indiscriminadamente todos os arquivos antigos para o projeto atual. Identifique as diferenças e recupere somente os elementos necessários, preservando a arquitetura funcional atual.

## 3. Documentação do TI — DIAGNÓSTICO E OTIMIZAÇÕES

`C:\Users\PC\OneDrive\Documentos\Pluviometro\docs`

Esta pasta contém a documentação relacionada ao diagnóstico e às alterações realizadas pelo departamento de TI para otimização do sistema.

Localize o PDF existente nesse diretório e faça sua leitura integral.

Analise todas as informações disponíveis, incluindo:

- Diagnóstico inicial.
- Problemas identificados.
- Alterações realizadas.
- Otimizações aplicadas.
- Arquivos modificados.
- Configurações alteradas.
- Melhorias de desempenho.
- Recomendações técnicas.
- Limitações conhecidas.

Compare o conteúdo do documento com a implementação atual.

**As otimizações válidas realizadas pelo TI devem ser preservadas.**

Não reverta nenhuma alteração sem antes compreender sua finalidade e avaliar seus impactos.

Se houver mais de um PDF, examine todos os documentos relevantes e identifique suas datas ou versões.

Se não localizar o documento esperado, informe exatamente o que encontrou. Não presuma seu conteúdo.

---

# REGRAS DE UTILIZAÇÃO DOS DIRETÓRIOS

A relação entre as três pastas é a seguinte:

| Diretório | Finalidade | Pode modificar? |
|---|---|---|
| `Pluviometro` | Projeto atual | Sim |
| `backup\...\monitor-pluviometro` | Referência visual antiga | Não |
| `docs` | Documentação e diagnóstico do TI | Não |

Antes de iniciar a implementação:

1. Confirme que está trabalhando no diretório correto.
2. Confirme que conseguiu acessar o backup visual.
3. Confirme que conseguiu localizar e ler o PDF do TI.
4. Compare a interface atual com a antiga.
5. Faça uma cópia de segurança do projeto atual antes das alterações.
6. Apresente um diagnóstico inicial com as diferenças encontradas.

**Não crie um projeto paralelo, não modifique o backup e não sobrescreva os documentos de diagnóstico.**

# 2. REDUZIR A POLUIÇÃO VISUAL

Atualmente, a interface está muito carregada de informações.

Quero uma interface mais limpa, objetiva e profissional, adequada para utilização em um laboratório de calibração.

A prioridade deve ser mostrar as informações realmente necessárias para a operação.

Evite:

- Excesso de cards.
- Informações repetidas.
- Muitos indicadores simultâneos.
- Textos explicativos ocupando espaço desnecessariamente.
- Informações técnicas secundárias competindo com os valores principais.
- Muitos elementos visuais chamando atenção ao mesmo tempo.

Organize as informações por importância.

Os valores principais devem ter destaque. Informações secundárias podem ficar em áreas recolhíveis, detalhes, configurações ou históricos.

Não elimine funcionalidades importantes simplesmente para deixar a interface mais limpa.

Quero uma interface minimalista, mas funcional.

# 3. CARD PRINCIPAL AZUL — COMPORTAMENTO CONFORME O MÉTODO DE CALIBRAÇÃO

Atualmente existe um card principal azul onde são exibidas as informações da balança.

Quero alterar o comportamento desse card.

O card deve apresentar automaticamente o instrumento correspondente ao método selecionado.

## Método gravimétrico

Quando o usuário selecionar o método gravimétrico, o card principal azul deve apresentar as informações da balança, mantendo o comportamento que já existe.

## Método comparativo

Quando o usuário selecionar o método comparativo, o mesmo card azul deve ser substituído pelo Medidor de Vazão.

Ou seja, não quero criar um segundo card azul permanente.

Quero que o card principal seja dinâmico:

- Método gravimétrico → exibe a balança.
- Método comparativo → exibe o medidor de vazão.

O comportamento deve ser semelhante ao que já acontece quando seleciono o método gravimétrico.

Ao alternar entre os métodos, a interface deve atualizar corretamente, sem recarregar a página inteira e sem perder configurações ou estados que precisem ser preservados.

O card deve manter a mesma identidade visual, dimensões, hierarquia e padrão de apresentação.

No método comparativo, o card deve priorizar as informações relevantes do medidor:

- Vazão instantânea.
- Unidade configurada.
- Corrente, quando estiver utilizando aquisição analógica.
- Pulsos brutos, quando estiver utilizando aquisição por pulsos.
- Estado da comunicação.
- Estado da aquisição.

Não exiba informações que não sejam pertinentes ao modo selecionado.

# 4. AQUISIÇÃO POR PULSOS — EXIBIR O VALOR BRUTO

Este é um dos pontos mais importantes desta atualização.

Atualmente, o sistema está exibindo um valor de pulsos convertido.

Não quero isso.

Quero que o sistema apresente o número bruto de pulsos efetivamente recebidos pelo datalogger.

O objetivo é utilizar a quantidade total de pulsos acumulados durante um ensaio de calibração.

Exemplo:

Durante um ensaio de 60 segundos, o medidor envia 1.250 pulsos.

O sistema deve apresentar:

- Pulsos acumulados: 1.250.
- Tempo decorrido: 60 segundos.
- Vazão calculada: determinada a partir dos pulsos e do fator K configurado.

Não quero que o sistema transforme antecipadamente os pulsos em litros, metros cúbicos ou outra unidade.

A contagem bruta deve ser preservada.

## 4.1. Comportamento durante o ensaio

Ao clicar em "Iniciar calibração":

1. Registrar o instante exato de início do ensaio.
2. Iniciar ou zerar a contagem relativa ao ensaio, sem apagar os registros históricos do datalogger.
3. Acumular os pulsos recebidos durante o período.
4. Medir o tempo efetivamente transcorrido.
5. Ao finalizar o ensaio, congelar os resultados.
6. Apresentar a quantidade total de pulsos e o tempo efetivo.
7. Calcular a vazão a partir desses valores.

O contador deve ser relativo ao ensaio, não necessariamente o contador absoluto do datalogger.

Se o datalogger fornecer um contador acumulativo, utilize a diferença entre o contador final e o inicial:

N = Contador_final - Contador_inicial

Não confunda o contador absoluto do datalogger com a quantidade de pulsos recebidos durante o ensaio.

Também é necessário tratar corretamente:

- Reinicialização do datalogger.
- Perda de comunicação.
- Lacunas de registros.
- Contador que retorna a zero.
- Transbordamento do contador.
- Pulsos recebidos antes do início do ensaio.
- Pulsos recebidos depois do encerramento.

Não permita que uma falha de comunicação seja interpretada como ausência de pulsos.

Se não for possível determinar a contagem com segurança, sinalize o ensaio como inválido ou incompleto.

## 4.2. Cálculo da vazão

Investigue como o fator K está implementado atualmente.

O fator K deve representar a relação entre pulsos e volume, respeitando a unidade configurada.

Exemplo conceitual:

Se K = 100 pulsos/L e foram registrados 1.250 pulsos em 60 segundos:

Volume = 1.250 / 100 = 12,5 L

Vazão = 12,5 / 60 = 0,20833 L/s

A conversão para outras unidades deve ocorrer somente depois do cálculo, respeitando a unidade de referência e a unidade de exibição.

Não invente valores de fator K.

O fator K deve ser configurável pelo usuário e sua unidade deve ficar explícita.

Se o fator K for configurado em pulsos por litro, por exemplo, não interprete como pulsos por metro cúbico.

Implemente validações para evitar divisão por zero, fatores inválidos e unidades incompatíveis.

# 5. RESOLUÇÃO DO TEMPO — POSSIBILIDADE DE CONFIGURAÇÃO EM MILISSEGUNDOS

Quero investigar a possibilidade de aumentar a resolução temporal do sistema.

Atualmente, o ensaio trabalha com períodos em segundos.

Entretanto, para a calibração do temporizador do sistema, preciso de maior resolução.

Quero que seja possível configurar o tempo também em milissegundos.

Exemplos de períodos configuráveis:

- 1.000 ms.
- 500 ms.
- 250 ms.
- 100 ms.
- 50 ms.
- 10 ms.

Esses valores são exemplos de configuração desejada, não uma afirmação de que o hardware consegue executar todos eles com precisão.

**Antes de implementar, investigue a capacidade real do CR1000Xe e do programa CRBasic.**

Preciso que você verifique:

1. Qual é a resolução temporal real disponível no CR1000Xe.
2. Qual é a resolução dos timestamps dos registros.
3. Qual é o intervalo de execução do programa CRBasic.
4. Se a instrução de contagem de pulsos utilizada permite detectar pulsos em frequências maiores que a taxa de execução da tabela.
5. Se é possível medir intervalos menores que um segundo com precisão.
6. Se existe alguma limitação relacionada à frequência de aquisição, ao processamento ou à comunicação com o servidor.
7. Se é possível utilizar um temporizador interno de maior resolução.
8. Qual é a incerteza ou limitação prática introduzida pelo método de medição do tempo.

Não quero uma falsa precisão.

Se a interface permitir configurar 10 ms, mas o datalogger só conseguir medir com resolução efetiva de 100 ms, isso precisa ser informado claramente.

A resolução configurada, a resolução efetivamente alcançada e a resolução apresentada na interface não devem ser confundidas.

## 5.1. Configuração do período

Quero que o usuário consiga configurar o período do ensaio de maneira intuitiva.

Preferencialmente, permita selecionar a unidade de tempo:

- Milissegundos (ms).
- Segundos (s).
- Minutos (min).

O sistema deve converter internamente os valores para uma unidade consistente, sem perder precisão desnecessariamente.

A interface deve apresentar o tempo decorrido com casas decimais adequadas à resolução realmente disponível.

Exemplo:

Tempo configurado: 500 ms.

Tempo efetivamente medido: 498,7 ms.

Não arredonde prematuramente para 0 ou 1 segundo.

## 5.2. Medição e calibração do temporizador

Quero que você avalie como podemos utilizar o próprio sistema para verificar a precisão do temporizador.

O objetivo é comparar o tempo medido pelo CR1000Xe com uma referência externa de tempo, caso disponível.

Investigue se é possível registrar:

- Timestamp inicial.
- Timestamp final.
- Tempo decorrido calculado.
- Resolução temporal utilizada.
- Diferença entre tempo configurado e tempo efetivamente medido.

Não declare que o temporizador foi calibrado apenas porque o software mediu um intervalo.

A calibração metrológica exige comparação com uma referência adequada e avaliação dos resultados.

# 6. REVISÃO COMPLETA DO PROGRAMA DO PLUVIÔMETRO E DO HARDWARE

Quero que você revise absolutamente todo o programa utilizado no CR1000Xe.

Não se limite ao arquivo principal.

Procure e analise:

- Arquivos CRBasic.
- Versões anteriores do programa.
- Configurações de aquisição.
- Perfis JSON.
- Mapeamento das tabelas.
- Variáveis.
- Canais de entrada e saída.
- Comunicação serial.
- Comunicação analógica.
- Contagem de pulsos.
- Rotinas de temporização.
- Tabelas de armazenamento.
- Configuração de sensores.
- Integração com o servidor Python.
- Rotinas de interpretação dos dados.

Quero que você produza um levantamento técnico completo, identificando onde cada sensor está conectado e como cada informação chega à interface.

## 6.1. Datalogger utilizado

O equipamento utilizado é:

**Campbell Scientific CR1000Xe.**

Confirme essa informação nos arquivos do projeto e identifique a versão do sistema operacional e do programa, quando disponíveis.

Não confunda o CR1000Xe com outros modelos da Campbell Scientific.

## 6.2. Balança de precisão

A balança utilizada é a:

**Precision Balance MK MK30K1.**

A comunicação é feita por RS-232.

A pinagem utilizada anteriormente foi a pinagem serial padrão que adotamos, e não uma pinagem oficialmente confirmada por manual específico do fabricante.

A ligação utilizada foi:

- TX da balança → C6 do datalogger.
- RX da balança → C5 do datalogger.
- GND → G do datalogger.

A comunicação deve ser investigada nos arquivos CRBasic e na rotina Python responsável pela interpretação dos dados.

Não altere essa ligação sem uma justificativa técnica.

## 6.3. Termopar

O sensor de temperatura da água é um termopar tipo T.

A ligação utilizada é:

- Positivo → 1H.
- Negativo → 1L.

Identifique no programa a instrução de leitura, o canal, o tipo de termopar, a compensação de junta fria e o nome da variável enviada à tabela.

## 6.4. Pluviômetro

O pluviômetro utiliza contato seco.

A ligação utilizada é:

- Sinal → P1.
- Referência → G.

O sinal foi verificado em aproximadamente 5 V quando o contato está aberto.

O programa utiliza contagem de pulsos por fechamento de contato.

A configuração de aquisição deve ser verificada diretamente no CRBasic, especialmente o parâmetro de configuração do pulso e a utilização de pull-up.

A resolução configurada atualmente é de 0,2 mm por basculada, mas confirme esse valor nos arquivos.

Não altere o funcionamento do pluviômetro original sem necessidade.

## 6.5. Medidor de vazão — saída analógica 4–20 mA

O sistema possui integração com um transmissor de vazão Siemens SITRANS FM MAG 5000.

A aquisição analógica foi implementada e está funcionando.

O programa utiliza a entrada diferencial 2H/2L do CR1000Xe e uma resistência de shunt para converter a corrente em tensão.

A lógica implementada deve ser investigada, incluindo:

- Medição de tensão diferencial.
- Resistência do shunt.
- Conversão de mV para mA.
- Faixa de 4–20 mA.
- Variáveis CRBasic.
- Tabela de aquisição.
- Mapeamento no perfil JSON.
- Conversão de corrente em vazão no Python.
- Unidade configurada.
- Unidade exibida.
- Tratamento de sinal fora da faixa.

Não altere a aquisição analógica que já está funcionando.

O modo analógico deve continuar funcionando exatamente como antes, mesmo depois da implementação da aquisição por pulsos.

## 6.6. Aquisição por pulsos do medidor de vazão

Quero que você investigue como implementar a aquisição por pulsos do medidor de vazão.

Não presuma que a saída digital do MAG 5000 tenha determinado tipo elétrico.

Não presuma que os terminais de saída sejam compatíveis diretamente com o CR1000Xe.

Não invente pinagens.

Se os arquivos disponíveis não forem suficientes, identifique exatamente qual informação ou manual é necessário para confirmar:

- Tipo de saída digital.
- Tensão.
- Corrente.
- Isolamento.
- Frequência máxima.
- Polaridade.
- Terminais.
- Necessidade de alimentação externa.
- Necessidade de resistor ou circuito de condicionamento.
- Compatibilidade com a entrada de pulsos do CR1000Xe.

A implementação deve ser modular, permitindo alternar entre:

- Modo analógico (4–20 mA).
- Modo pulsos.

A escolha deve ser feita na interface, preferencialmente dentro do card do Medidor de Vazão.

Não deixe o usuário precisar editar manualmente arquivos CRBasic ou JSON para trocar o modo de operação, se isso puder ser resolvido com segurança pela arquitetura do sistema.

Entretanto, se a mudança de modo exigir alteração e envio de um novo programa ao datalogger, explique essa limitação. Não simule uma alteração de hardware ou firmware apenas mudando um seletor visual.

# 7. REVISÃO DO PDF DE DIAGNÓSTICO DO TI

Na pasta do projeto existe um PDF contendo o diagnóstico das alterações realizadas pelo departamento de TI para otimização do sistema.

Esse documento é muito importante.

Localize e leia o PDF integralmente.

Não ignore anexos, tabelas, recomendações, observações ou limitações técnicas presentes no documento.

Quero que você identifique:

1. Quais alterações foram realizadas pelo TI.
2. Quais problemas existiam antes.
3. Quais otimizações foram aplicadas.
4. Quais arquivos foram modificados.
5. Quais configurações foram alteradas.
6. Quais melhorias de desempenho foram implementadas.
7. Quais riscos ou limitações ainda existem.
8. Quais dessas alterações precisam ser preservadas na próxima atualização.

Compare o diagnóstico com o código atual.

Não reverta otimizações do TI simplesmente porque parecem diferentes da arquitetura anterior.

Preserve as melhorias de desempenho que forem tecnicamente válidas.

Se o PDF não estiver disponível no diretório aberto, informe isso explicitamente e solicite sua localização. Não invente o conteúdo do documento.

# 8. ARQUITETURA DE SOFTWARE — REVISÃO COMPLETA

Quero que você mapeie o caminho completo dos dados:

**Sensor → CR1000Xe → CRBasic → Tabela do datalogger → DataQuery → Python → Flask → Socket.IO/API → JavaScript → Interface.**

Analise especialmente:

- app.py.
- datalogger.py.
- calc.py.
- trials.py.
- Perfis JSON.
- Arquivos JavaScript.
- HTML.
- CSS.
- Banco de dados SQLite.
- Rotinas de histórico.
- Rotinas de ensaio.
- Rotinas de relatório.
- Comunicação com o datalogger.
- Tratamento de falhas.
- Atualização em tempo real.

Quero saber onde cada dado nasce, como é transformado e onde é apresentado.

Verifique também se há:

- Conversões duplicadas.
- Variáveis redundantes.
- Estados inconsistentes.
- Campos com nomes diferentes entre CRBasic e JSON.
- Erros de capitalização.
- Tratamento incorreto de unidades.
- Problemas de sincronização.
- Perda de registros.
- Uso desnecessário de consultas.
- Rotinas que possam causar lentidão.
- Código antigo que não é mais utilizado.

Não remova funcionalidades apenas por parecerem redundantes. Primeiro confirme se realmente não são utilizadas.

# 9. PRESERVAÇÃO DAS FUNCIONALIDADES EXISTENTES

Este requisito é obrigatório.

O sistema já possui funcionalidades operacionais e não quero perder o que já foi desenvolvido.

Preserve:

- Comunicação real com o CR1000Xe.
- Aquisição da balança.
- Aquisição do termopar.
- Aquisição do pluviômetro.
- Aquisição analógica 4–20 mA.
- Configuração de unidades.
- Configuração dos parâmetros de calibração.
- Histórico.
- Gráficos.
- Relatórios.
- Métodos gravimétrico e comparativo.
- Rotinas de ensaio.
- Identidade visual da Elus.
- Otimizações aplicadas pelo TI.

Não utilize dados fictícios para preencher a interface operacional.

Os dados apresentados devem vir das fontes reais do sistema.

Dados simulados podem existir exclusivamente nos testes automatizados, isolados do funcionamento normal.

Não substitua a comunicação real por mocks.

Não altere parâmetros físicos, fatores K, constantes, pinagens ou escalas sem confirmação documental ou validação técnica.

# 10. TESTES OBRIGATÓRIOS

Após implementar, faça uma bateria de testes.

## Interface

- Verificar a tipografia restaurada.
- Verificar responsividade.
- Verificar o comportamento do card principal azul.
- Alternar entre método gravimétrico e comparativo.
- Verificar se o card exibe o instrumento correto.
- Verificar se as informações não ficam duplicadas.
- Verificar se a interface continua limpa.

## Aquisição analógica

- Verificar se o modo 4–20 mA continua funcionando.
- Verificar a leitura da corrente.
- Verificar a conversão de corrente para vazão.
- Verificar diferentes unidades.
- Verificar os limites da faixa.
- Verificar valores fora da faixa.

## Aquisição por pulsos

Criar testes para:

- Nenhum pulso.
- Um pulso.
- Múltiplos pulsos.
- Contagem acumulada.
- Início do ensaio.
- Finalização do ensaio.
- Reinício do ensaio.
- Perda de comunicação.
- Lacunas de registros.
- Contador reiniciado.
- Períodos menores que um segundo.
- Cálculo de vazão.
- Conversão de unidades.

Verificar se a quantidade de pulsos exibida corresponde exatamente à quantidade acumulada durante o ensaio.

## Temporização

Testar os períodos configuráveis e comparar o tempo solicitado com o tempo efetivamente medido.

Não declare precisão que não tenha sido demonstrada.

Documente as limitações do hardware e do método de aquisição.

## Regressão

Execute todos os testes automatizados já existentes.

Não remova testes antigos apenas para fazer a suíte passar.

Se algum teste precisar ser atualizado por causa de uma mudança legítima, explique o motivo.

# 11. DOCUMENTAÇÃO FINAL

Ao terminar, quero uma documentação técnica com:

1. Resumo das alterações.
2. Arquivos modificados.
3. Arquivos novos.
4. Arquivos removidos, se houver.
5. Explicação das alterações na interface.
6. Explicação do funcionamento da contagem bruta de pulsos.
7. Fórmulas utilizadas.
8. Explicação da medição de tempo.
9. Resolução temporal efetivamente alcançada.
10. Limitações do CR1000Xe.
11. Mapeamento atualizado dos sensores e conexões.
12. Mapeamento das tabelas e variáveis.
13. Fluxo completo dos dados.
14. Resultado dos testes.
15. Problemas encontrados.
16. Pendências que dependem de informação ou validação física.

Quero também uma tabela de referência com:

| Equipamento | Tipo de sinal | Conexão no CR1000Xe | Variável CRBasic | Tabela |
|---|---|---|---|---|
| Balança MK30K1 | RS-232 | C5/C6/G | Confirmar no código | Confirmar |
| Termopar tipo T | Analógico | 1H/1L | Confirmar no código | Confirmar |
| Pluviômetro | Contato seco | P1/G | Confirmar no código | Confirmar |
| MAG 5000 | 4–20 mA | 2H/2L e shunt | Confirmar no código | Vazao1s ou confirmar |
| MAG 5000 | Pulsos | A confirmar | A implementar/verificar | A confirmar |

Não preencha lacunas com suposições. Identifique claramente o que foi confirmado no código, o que foi confirmado em documentação e o que ainda depende de validação física.

---

# 12. ORDEM DE EXECUÇÃO

Siga esta ordem:

**ETAPA 1 — DIAGNÓSTICO**

- Examinar a estrutura completa do projeto.
- Ler os arquivos CRBasic.
- Ler os perfis JSON.
- Ler a documentação.
- Ler o PDF do TI.
- Mapear o hardware.
- Identificar a arquitetura da interface.
- Comparar a identidade visual atual com a anterior.
- Identificar riscos e dependências.

**ETAPA 2 — PLANEJAMENTO**

Apresentar um plano técnico de implementação, separando:

- Alterações visuais.
- Alterações de interface.
- Alterações no backend.
- Alterações no CRBasic.
- Alterações de aquisição.
- Alterações de temporização.
- Testes necessários.

Identificar quais mudanças podem ser feitas apenas no software e quais exigem intervenção no datalogger ou na instalação física.

**ETAPA 3 — IMPLEMENTAÇÃO**

Executar as alterações sem comprometer as funcionalidades existentes.

Priorizar uma arquitetura modular e de fácil manutenção.

**ETAPA 4 — TESTES**

Executar a suíte de testes e os testes específicos das novas funcionalidades.

**ETAPA 5 — DOCUMENTAÇÃO**

Entregar a documentação técnica completa e informar o que está funcionando, o que foi testado e o que ainda depende de validação física.

---

# DIRETRIZES FINAIS

- Trabalhe diretamente no projeto aberto no VS Code.
- Não crie um segundo projeto paralelo.
- Não substitua a arquitetura inteira sem necessidade.
- Não faça alterações cosméticas que prejudiquem a legibilidade.
- Não invente dados, parâmetros ou conexões.
- Não altere a aquisição analógica funcional.
- Não confunda pulsos brutos com volume convertido.
- Não confunda resolução de exibição com resolução real de medição.
- Não considere uma simulação como validação de hardware.
- Faça alterações organizadas e documentadas.
- Preserve o histórico e os dados existentes.
- Antes de alterar arquivos importantes, mantenha uma forma de recuperação da versão anterior.

**O objetivo final é ter um sistema de calibração profissional, visualmente limpo, tecnicamente confiável e preparado para trabalhar tanto com medidores de vazão analógicos (4–20 mA) quanto com medidores de saída por pulsos, mantendo o CR1000Xe como fonte real de aquisição.**

Quero que você trabalhe com o rigor de um desenvolvedor de sistemas de aquisição de dados industriais e de um profissional de instrumentação e metrologia. A prioridade não é simplesmente fazer a interface funcionar, mas garantir que os valores apresentados tenham origem conhecida, cálculo correto e resolução compatível com a capacidade real dos instrumentos.