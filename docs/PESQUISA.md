# Pesquisa técnica e escolha da arquitetura

Fontes consultadas (oficiais da Campbell Scientific):

- CSI Datalogger Web Service API (v1.00.11, abr/2021): https://s.campbellsci.com/kb/7427_20210817014204.pdf — **lido para o DataQuery**
- CRBasic Help, `TCPOpen` (CR1000X): https://help.campbellsci.com/crbasic/cr1000x/Content/Instructions/tcpopen.htm
- CRBasic Help, `HTTPPost` (CR1000X): https://help.campbellsci.com/crbasic/cr1000x/Content/Instructions/httppost.htm
- Página do produto: https://www.campbellsci.com.br/cr1000x
- LoggerNet Admin: https://www.campbellsci.com/loggernet-admin
- Artigo "web api" (https://www.campbellsci.com/web-api-article): a página deu 404 na consulta; não foi usada.
- Vídeo da interface web (https://www.campbellsci.com/videos/web-interface): só apareceu na busca; **não foi assistido**.
- Não li o manual completo do CR1000X nem o Getting Started Guide.

## O que a documentação confirma

| Item | Confirmado | Fonte |
|---|---|---|
| `DataQuery` com `mode=since-record`, `most-recent`, `since-time`, `date-range`, `backfill` | Sim | Web Service API §2.1.1 |
| `since-record`: registros com número ≥ `p1`; se o número não existe mais, começa pelo mais antigo da tabela | Sim | idem |
| `format=json` (CsiJSON): `head.fields`, `data[].no/time/vals`, `more` | Sim | idem e exemplos §2.1.3.2 |
| O servidor pode dividir a resposta e avisa com `more` | Sim | idem |
| Autenticação Basic; contas em `.csipasswd`; nível 3 = somente leitura; HTTPS possível | Sim | §1.2 |
| `p3` como tamanho de página | **Não consta** | por isso foi removido do código |
| Como `NAN` aparece no JSON | **Não consta** nas partes lidas; o código aceita o texto `"NAN"` e número | validar no seu equipamento |
| `TCPOpen` como cliente TCP; bloqueia até conectar ou estourar o timeout (padrão 75 s); pode ir em `SlowSequence` | Sim | CRBasic Help |
| `HTTPPost` com HTTP e HTTPS | Sim | CRBasic Help |
| API Python oficial do LoggerNet | **Não encontrada** | busca |

## Comparação

| Arquitetura | Compatibilidade confirmada | Complexidade | Vantagens | Limitações |
|---|---|---|---|---|
| A. CR1000Xe envia ao Python (`TCPOpen`/`HTTPPost`) | Instruções existem no CRBasic Help do CR1000X | Alta | Tempo real sem polling | Bloqueia o scan até 75 s se o servidor cair (exige `SlowSequence`); o datalogger não guarda o que não enviou; altera o programa que já funciona; não verifiquei o comportamento com o OS 8.2 |
| **B. Python consulta a API web (escolhida)** | Sim (Web Service API, DataQuery) | Baixa | Não altera o CRBasic; recupera pelo número do registro, sem duplicar; sem software extra | Depende de rede e HTTP habilitado; tabelas circulares (20.000 registros a 1 Hz ≈ 5,5 h) |
| C. LoggerNet como intermediário | LoggerNet coleta CR1000X; sem API Python oficial encontrada | Média/alta | Histórico longo | Licença e instalação; leitura via arquivos ou SDK de terceiros; mais uma peça para falhar |

**Escolha: B.** Não mexe na balança, no termopar nem no pluviômetro, não bloqueia a aquisição se a rede cair e o projeto já a implementava, com cursor em disco. C passa a valer se a calibração precisar de histórico além de ~5,5 h com o servidor desligado.

**Nada foi testado contra um CR1000Xe real.** Os testes usam emuladores que seguem a documentação acima.
