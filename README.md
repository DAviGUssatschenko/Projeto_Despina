# Projeto Despina — Análise de Sinistros Agrícolas via Sensoriamento Remoto

Pipeline completo para validação de sinistros agrícolas (seca, chuva excessiva, geada, granizo) usando imagens Sentinel-2 do Copernicus e dados climáticos de banco de dados histórico.

---

## Estrutura do projeto
```
projeto_seca/
├── data/
│   ├── raw/              # Excel original (não versionado)
│   ├── processed/        # CSVs e TIFs gerados pelos scripts
│   └── external/         # Dados de terceiros (shapefiles, etc)
├── docs/
│   └── guia_indices.docx
├── notebooks/
├── references/
│   └── interpretacao_indices.md
├── reports/figures/
└── src/seca/
    ├── data/
    │   ├── fetch_climate.py
    │   └── fetch_copernicus.py
    ├── features/
    │   └── split_tifs.py
    └── visualization/
        └── plot_indices.py
```

---

## Instalação
```bash
git clone https://github.com/SEU-USUARIO/projeto_seca.git
cd projeto_seca
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

---

## Configuração

### Banco de dados
Edite `src/seca/data/fetch_climate.py` e ajuste o bloco `DB_CONFIG` com host, porta, banco, usuário e senha.

### Copernicus
Crie um OAuth client em [shapps.dataspace.copernicus.eu](https://shapps.dataspace.copernicus.eu/dashboard) → User Settings → OAuth Clients e edite `CLIENT_ID` e `CLIENT_SECRET` em `fetch_copernicus.py`.

---

## Uso
```bash
# 1. Extrai dados climáticos do PostgreSQL
python src/seca/data/fetch_climate.py

# 2. Baixa índices de satélite do Copernicus
python src/seca/data/fetch_copernicus.py

# 3. Separa TIFs multi-banda em 1 banda por arquivo
python src/seca/features/split_tifs.py

# 4. Gera imagens PNG e painéis temporais
python src/seca/visualization/plot_indices.py
```

---

## Índices calculados

| Índice | O que mede | Sobe = | Cai = |
|--------|------------|--------|-------|
| **NBR** | Estresse severo / saúde geral | Saudável | Seca/queimada |
| **NDRE** | Clorofila via Red-Edge | Clorofila alta | Amarelamento |
| **MSI** | Estresse hídrico foliar | **Mais seco** ⚠️ | Mais úmido |
| **GNDVI** | Biomassa / N foliar | Vigor alto | Estresse |
| **SAVI** | Cobertura vegetal (corr. solo) | Lavoura fechada | Solo exposto |
| **NDDI** | Índice de seca combinado | Seca intensa | Umidade |

---

## Licença

MIT
```

5. Clique em **Commit changes** → **Commit changes** (confirma)

---
