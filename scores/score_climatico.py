import pandas as pd
import numpy as np
from .normalizacao import normalizar_minmax


def calcular_score_climatico_municipio(
    df_focos: pd.DataFrame,
    municipio: str,
) -> dict:
    """
    Calcula score climático usando dados do próprio CSV do INPE:
    - numero_dias_sem_chuva
    - precipitacao
    - risco_fogo (meteorológico do INPE)

    C = 0.40*Ch + 0.35*RF + 0.25*DSC
    Ch = déficit de chuva (precipitação baixa → risco alto)
    RF = risco de fogo meteorológico do INPE
    DSC = dias sem chuva
    """
    focos_mun = df_focos[df_focos["municipio"].str.upper() == municipio.upper()]

    if focos_mun.empty:
        return {"municipio": municipio, "C_disponivel": False}

    dias_sem_chuva = pd.to_numeric(focos_mun["numero_dias_sem_chuva"], errors="coerce")
    dias_sem_chuva = dias_sem_chuva[dias_sem_chuva >= 0]

    precipitacao = pd.to_numeric(focos_mun["precipitacao"], errors="coerce")
    precipitacao = precipitacao[precipitacao >= 0]

    risco_fogo = pd.to_numeric(focos_mun["risco_fogo"], errors="coerce")
    risco_fogo = risco_fogo[risco_fogo >= 0]

    dsc_medio = dias_sem_chuva.mean() if not dias_sem_chuva.empty else None
    precip_media = precipitacao.mean() if not precipitacao.empty else None
    rf_medio = risco_fogo.mean() if not risco_fogo.empty else None

    return {
        "municipio": municipio,
        "C_disponivel": True,
        "dias_sem_chuva_medio": round(dsc_medio, 1) if dsc_medio is not None else None,
        "precipitacao_media": round(precip_media, 2) if precip_media is not None else None,
        "risco_fogo_meteo": round(rf_medio, 3) if rf_medio is not None else None,
        "DSC_raw": dsc_medio if dsc_medio is not None else 0,
        "Ch_raw": precip_media if precip_media is not None else 0,
        "RF_raw": rf_medio if rf_medio is not None else 0,
    }


def calcular_score_climatico_normalizado(
    resultados_municipios: list[dict],
) -> pd.DataFrame:
    """
    Normaliza e calcula C = 0.40*Ch + 0.35*RF + 0.25*DSC.
    Ch é invertido: menos chuva = mais risco.
    """
    df = pd.DataFrame(resultados_municipios)

    df["DSC"] = normalizar_minmax(df["DSC_raw"].astype(float)).fillna(0)
    df["Ch"] = normalizar_minmax(df["Ch_raw"].astype(float), inverter=True).fillna(0)
    df["RF"] = normalizar_minmax(df["RF_raw"].astype(float)).fillna(0)

    df["C"] = (0.40 * df["Ch"] + 0.35 * df["RF"] + 0.25 * df["DSC"]).fillna(0).round(1)

    return df
