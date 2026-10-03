import numpy as np
import pandas as pd


def normalizar_minmax(serie: pd.Series, inverter: bool = False) -> pd.Series:
    """Normalização min-max com percentis p05/p95, escala 0-100."""
    p05 = serie.quantile(0.05)
    p95 = serie.quantile(0.95)

    if p95 == p05:
        return pd.Series(50.0, index=serie.index)

    n = 100 * (serie - p05) / (p95 - p05)
    n = n.clip(0, 100)

    if inverter:
        n = 100 - n

    return n


def normalizar_faixas(serie: pd.Series) -> pd.Series:
    """Normalização por faixas de percentis (P25/P50/P75)."""
    p25 = serie.quantile(0.25)
    p50 = serie.quantile(0.50)
    p75 = serie.quantile(0.75)

    conditions = [
        serie <= p25,
        (serie > p25) & (serie <= p50),
        (serie > p50) & (serie <= p75),
        serie > p75,
    ]
    choices = [25, 50, 75, 100]

    return pd.Series(np.select(conditions, choices, default=0), index=serie.index, dtype=float)


def score_proximidade_foco(distancia_km: float) -> float:
    """Score de proximidade entre foco e pivô (tabela do spec)."""
    if distancia_km <= 1:
        return 100
    elif distancia_km <= 3:
        return 75
    elif distancia_km <= 5:
        return 50
    elif distancia_km <= 10:
        return 25
    else:
        return 0


def score_sensibilidade_ambiental(distancia_km: float) -> float:
    """Score de proximidade a área protegida (tabela do spec)."""
    if distancia_km <= 0:
        return 100
    elif distancia_km <= 5:
        return 75
    elif distancia_km <= 10:
        return 50
    elif distancia_km <= 20:
        return 25
    else:
        return 0
