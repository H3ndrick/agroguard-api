# AgroGuard

Plataforma de análise de risco ambiental e aptidão agrícola para áreas irrigadas no Brasil. Combina dados públicos de queimadas, clima, irrigação, seguro rural e zoneamento agrícola para gerar scores de risco (0-100) por município.

## O que faz

O AgroGuard recebe coordenadas geográficas (ou nome do município), identifica o município via ponto-em-polígono e calcula dois scores independentes:

### Score de Risco Ambiental (0-100)
Mede o quanto um município está exposto a riscos de queimadas e condições adversas.

- **Fogo (F)**: focos de calor nos últimos 7/30 dias, total anual e intensidade (FRP)
- **Clima (C)**: dias sem chuva, precipitação e risco meteorológico de fogo
- **Agrícola (A)**: hectares irrigados, pivôs centrais e seguro rural (SISSER)
- **Ambiental (S)**: proximidade de áreas protegidas *(dados pendentes)*

Fórmula: `R = 0.40*F + 0.25*C + 0.20*A + 0.15*S` (com redistribuição de pesos quando um componente não tem dados)

### Score de Aptidão Agrícola (0-100)
Mede o potencial agrícola climático do município com base no ZARC.

- Taxa de aptidão geral e de sequeiro
- Diversidade de culturas viáveis

Fórmula: `ZARC = 0.50*Aptidão_sequeiro + 0.30*Aptidão_geral + 0.20*Diversidade_culturas`

## Fontes de dados

| Fonte | Descrição | Cobertura |
|-------|-----------|-----------|
| [INPE BDQueimadas](https://dataserver-coids.inpe.br/queimadas/queimadas/focos/csv/mensal/Brasil/) | Focos de calor por satélite (NOAA-20/21, GOES-19, NPP, AQUA/TERRA) | Brasil, 2025-2026 (5.5M focos) |
| [ANA/Embrapa](https://metadados.snirh.gov.br/geonetwork/) | Pivôs centrais — área irrigada por município (1985-2022) | Brasil (1.282 municípios) |
| [MAPA SISSER/PSR](https://dados.agricultura.gov.br/) | Programa de Subvenção ao Prêmio do Seguro Rural | Brasil (46.137 apólices) |
| [MAPA ZARC](https://dados.agricultura.gov.br/) | Zoneamento Agrícola de Risco Climático — aptidão por cultura/decêndio | Brasil (931k registros) |
| [IBGE](https://servicodados.ibge.gov.br/) | Malha municipal simplificada + nomes | Brasil (5.570 municípios) |

## Arquitetura

```
agroguard/
├── api.py                          # FastAPI — endpoints e orquestração
├── scores/
│   ├── normalizacao.py             # Min-max com p05/p95, faixas percentílicas
│   ├── score_fogo.py               # F = 0.375*F7 + 0.250*F30 + 0.250*F_ano + 0.125*I
│   ├── score_climatico.py          # C = 0.40*Chuva + 0.35*RiscoFogo + 0.25*DiasSemChuva
│   ├── score_agricola.py           # A = 0.50*Hectares + 0.30*QtdPivos + 0.20*Densidade
│   ├── score_sisser.py             # SIS = 0.40*Area + 0.35*Valor + 0.25*Apólices
│   ├── score_zarc.py               # ZARC = aptidão agrícola climática
│   └── score_geral.py              # R, P, relatório completo com sub-scores
├── static/
│   └── index.html                  # Frontend — Leaflet, seletor de estado/município
├── data/raw/                       # Dados brutos (não versionados)
│   ├── focos_br_2025.csv           # 3.4M focos
│   ├── focos_br_2026.csv           # 2.0M focos
│   ├── municipios_br.json          # Malha IBGE simplificada
│   ├── municipios_br_nomes.csv     # Código/nome/UF
│   ├── pivos_area_municipio_1985_2022.xlsx
│   ├── sisser_psr_2025.csv
│   └── zarc_2024_2025.csv
└── tests/
    ├── test_normalizacao.py
    └── test_score_fogo.py
```

## Como funciona

1. **Startup**: carrega todos os dados globais (focos BR, pivôs, SISSER, ZARC, malha municipal) e pré-calcula contornos dos 27 estados
2. **Seleção de estado**: o endpoint `/estado/{uf}` calcula scores de fogo, clima, agrícola, SISSER e ZARC para todos os municípios daquele estado, cacheia na memória
3. **Consulta**: o endpoint `/score?lat=X&lon=Y&uf=UF` localiza o município por ponto-em-polígono e retorna o relatório completo com todos os sub-scores e fatores explicativos
4. **Normalização**: todos os indicadores passam por min-max com percentis 5/95 para evitar outliers, escala 0-100
5. **Peso redistribuído**: quando um componente não tem dados (ex: município sem pivôs), seu peso é redistribuído entre os outros — `None ≠ 0`

## Reproduzir localmente

### Pré-requisitos

- Python 3.10+
- ~1GB de espaço em disco para os dados

### 1. Instalar dependências

```bash
pip install fastapi uvicorn geopandas pandas shapely openpyxl
```

### 2. Obter dados

#### Focos de calor (INPE)
Os CSVs mensais são públicos e baixados automaticamente:
```bash
mkdir -p data/raw
# Exemplo: baixar todos os meses de 2025
for m in $(seq -w 1 12); do
  curl -o /tmp/focos_${m}.csv \
    "https://dataserver-coids.inpe.br/queimadas/queimadas/focos/csv/mensal/Brasil/focos_mensal_br_2025${m}.csv"
  [ "$m" = "01" ] && head -1 /tmp/focos_${m}.csv > data/raw/focos_br_2025.csv
  tail -n +2 /tmp/focos_${m}.csv >> data/raw/focos_br_2025.csv
  rm /tmp/focos_${m}.csv
done
```

#### Malha municipal (IBGE)
```bash
curl -o data/raw/municipios_br.json \
  "https://servicodados.ibge.gov.br/api/v3/malhas/paises/BR?formato=application/vnd.geo+json&qualidade=minima&intrarregiao=municipio"
```

#### Nomes dos municípios (IBGE)
```bash
curl -s "https://servicodados.ibge.gov.br/api/v1/localidades/municipios" | \
  python3 -c "
import json, sys, csv
data = json.load(sys.stdin)
with open('data/raw/municipios_br_nomes.csv', 'w', newline='') as f:
    w = csv.writer(f)
    w.writerow(['codigo','nome','uf'])
    for m in data:
        try: uf = m['microrregiao']['mesorregiao']['UF']['sigla']
        except: uf = m['regiao-imediata']['regiao-intermediaria']['UF']['sigla']
        w.writerow([str(m['id']), m['nome'], uf])
"
```

#### Pivôs centrais (ANA/Embrapa)
Baixar manualmente em [metadados.snirh.gov.br](https://metadados.snirh.gov.br/geonetwork/srv/por/catalog.search#/metadata/e2e1a29a-adf4-4a50-97f4-44e8e5cf2346):
- Arquivo: `pivos_area_municipio_1985_2022.xlsx`
- Salvar em `data/raw/`

#### SISSER e ZARC (MAPA)
Baixar manualmente em [dados.agricultura.gov.br](https://dados.agricultura.gov.br/):
- SISSER PSR → `data/raw/sisser_psr_2025.csv`
- ZARC → `data/raw/zarc_2024_2025.csv`

### 3. Rodar

```bash
cd agroguard
python3 -m uvicorn api:app --host 0.0.0.0 --port 8000
```

Acesse http://localhost:8000 — selecione um estado, busque o município e consulte o score.

### 4. Testes

```bash
python3 -m pytest tests/ -v
```

## API

| Endpoint | Descrição |
|----------|-----------|
| `GET /` | Frontend (mapa + busca) |
| `GET /estados` | Lista os 27 estados com coordenadas centrais |
| `GET /estado/{uf}` | Carrega estado: municípios, contorno, stats |
| `GET /score?lat=X&lon=Y&uf=UF` | Score completo do município nas coordenadas |
| `GET /health` | Status do servidor |

### Exemplo de resposta `/score`

```json
{
  "municipio": "Rio Verde",
  "uf": "GO",
  "score_geral": 54.1,
  "classe_risco": "Moderado",
  "score_prioridade": 43.8,
  "indices": {
    "fogo": {"score_F": 48.5, "focos_7d": 12, "focos_30d": 223, "focos_total_ano": 2004},
    "climatico": {"score_C": 65.2, "dias_sem_chuva": 15},
    "agricola": {"score_A": 72.1, "hectares_irrigados": 45230, "qtd_pivos_estimada": 377}
  },
  "aptidao": {
    "score_aptidao": 81.9,
    "classe_aptidao": ["Excelente", "Verde escuro"],
    "zarc": {"taxa_aptidao": 16.2, "taxa_aptidao_sequeiro": 15.7, "n_culturas_aptas": 19}
  },
  "fatores_risco": ["223 focos nos últimos 30 dias", "45230 ha irrigados expostos"]
}
```

## Conceitos-chave

- **Score alto = mais risco** (no tema Risco Ambiental)
- **Score alto = melhor aptidão** (no tema Aptidão Agrícola)
- **None ≠ 0**: dado ausente redistribui peso; dado zero mantém peso na fórmula
- **Normalização p05/p95**: evita que outliers extremos distorçam a escala
- **Cache por estado**: primeiro acesso calcula tudo (~10-45s dependendo do estado), depois instantâneo

## Dados pendentes (próximos passos)

- ICMBio — Unidades de Conservação (score Ambiental S)
- FUNAI — Terras Indígenas (score Ambiental S)
- ANA — Shapefile dos pivôs centrais (score Proximidade P — distância foco↔pivô)
- INMET — Estações meteorológicas (melhorar score Climático C)
