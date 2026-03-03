# Referência Rápida — Índices de Satélite

## Tabela de interpretação rápida

| Índice | Sobe = | Cai = | Zera = | Explode = |
|--------|--------|-------|--------|-----------|
| **NBR** | Vegetação saudável | Seca / queimada | Solo exposto | < −0.2: dano severo |
| **NDRE** | Clorofila alta | Estresse / morte | Planta morta | n/a |
| **MSI** | Mais **SECO** ⚠️ | Mais úmido | Água / alagamento | > 2: solo seco |
| **GNDVI** | Biomassa / N foliar | Estresse / seca | Solo nu | n/a |
| **SAVI** | Cobertura vegetal | Lavoura falhando | Solo predominante | n/a |
| **NDDI** | Seca se intensifica | Chuva / umidade | Área mista | > 0.7: seca extrema |

---

## Diagnóstico por tipo de sinistro

### SECA — aceitar quando:
- NBR < 0.2 e estável ou caindo
- MSI p75 > 1.2 em pelo menos metade das imagens
- NDDI subindo progressivamente
- NDRE < 0.25 durante todo o período
- SAVI muito abaixo do esperado para o estágio da cultura

### ENCHENTE — aceitar quando:
- NDWI explode positivo (> 0.3) na data do evento
- MSI despenca para < 0.4
- NBR cai abruptamente em 1–2 imagens

### GEADA — aceitar quando:
- NDRE cai abruptamente em 1 única imagem
- Queda gradual ao longo de semanas = NÃO é geada

### GRANIZO — aceitar quando:
- Queda brusca em 1 imagem + std aumenta muito (dano heterogêneo)

---

## Por que não usar só NDVI/NDWI?

| Limitação | NDVI | Solução |
|-----------|------|---------|
| Detecta estresse só tarde | ✗ | **NDRE** (5–15 dias antes) |
| Satura em alta densidade | ✗ | **NBR / GNDVI** |
| Interferência do solo exposto | ✗ | **SAVI** |
| Não mede água foliar | ✗ | **MSI** |
| Sinal de seca fraco | ✗ | **NDDI** |
```

4. **Commit changes**

---
