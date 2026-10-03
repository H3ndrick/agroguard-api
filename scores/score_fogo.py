import math
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from .normalizacao import normalizar_minmax


def carregar_focos(caminho_csv: str) -> pd.DataFrame:
    df = pd.read_csv(caminho_csv)
    df["data_hora_gmt"] = pd.to_datetime(df["data_hora_gmt"])
    df["lat"] = df["lat"].astype(float)
    df["lon"] = df["lon"].astype(float)

    for col in ["frp", "risco_fogo"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
            df.loc[df[col] < 0, col] = np.nan

    for col in ["numero_dias_sem_chuva", "precipitacao"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
            df.loc[df[col] < 0, col] = np.nan

    return df


def _calcular_pse(dias_sem_chuva: float, precipitacao: float) -> float:
    """
    Aproximação do PSE (Período Seco Equivalente) do INPE v11.
    Usa dias_sem_chuva como proxy principal e precipitacao como atenuante.
    PSE = dias_sem_chuva * fator_precipitacao
    """
    if pd.isna(dias_sem_chuva) or dias_sem_chuva < 0:
        return 0.0
    fp = math.exp(-0.04 * max(precipitacao, 0)) if not pd.isna(precipitacao) else 1.0
    return dias_sem_chuva * fp


def _risco_basico_vegetacao(pse: float, tipo_veg: int = 2) -> float:
    """
    Rb do INPE: Risco Básico por tipo de vegetação.
    Rb = 0.8 * (1 + sin((A * PSE - 90) * pi/180)) / 2

    Coeficientes A por tipo (aproximados da curva da publicação):
    1=Pastagens(6.0), 2=Agricultura(3.5), 3=Savana/Caatinga aberta(2.5),
    4=Savana arbórea/Caatinga fechada(1.8), 5=Floresta contato(1.2),
    6=Florestas decíduas(0.9), 7=Ombrófila densa(0.6)
    """
    coefs = {0: 0.0, 1: 6.0, 2: 3.5, 3: 2.5, 4: 1.8, 5: 1.2, 6: 0.9, 7: 0.6}
    a = coefs.get(tipo_veg, 3.5)
    if a == 0 or pse <= 0:
        return 0.0
    ang_rad = (a * pse - 90) * (math.pi / 180)
    rb = 0.8 * (1 + math.sin(ang_rad)) / 2
    return max(0.0, min(rb, 0.8))


def _fator_temperatura(tmax: float = 30.0) -> float:
    """FT = (Tmax * 0.02) + 0.4"""
    return (tmax * 0.02) + 0.4


def _fator_umidade(ur: float = 50.0) -> float:
    """FU = (UR * -0.006) + 1.3"""
    return (ur * -0.006) + 1.3


def calcular_rf_inpe(dias_sem_chuva: float, precipitacao: float,
                     tmax: float = 30.0, ur: float = 50.0,
                     tipo_veg: int = 2) -> float:
    """
    Calcula o Risco de Fogo (RF) pela fórmula INPE v11:
    RF = Rb × FT × FU
    Resultado entre 0 e 1.
    """
    pse = _calcular_pse(dias_sem_chuva, precipitacao)
    rb = _risco_basico_vegetacao(pse, tipo_veg)
    ft = _fator_temperatura(tmax)
    fu = _fator_umidade(ur)
    rf = rb * ft * fu
    return max(0.0, min(rf, 1.0))


def classificar_rf_inpe(rf: float) -> str:
    if rf < 0.15:
        return "Mínimo"
    elif rf <= 0.40:
        return "Baixo"
    elif rf <= 0.70:
        return "Médio"
    elif rf <= 0.95:
        return "Alto"
    else:
        return "Crítico"


def calcular_score_fogo_municipio(
    df_focos: pd.DataFrame,
    municipio: str,
    data_referencia: datetime | None = None,
) -> dict:
    """
    Calcula o score de fogo usando o método INPE como base primária.

    1. RF_inpe: risco_fogo do INPE (já calculado pelo próprio INPE) → peso 0.60
    2. Focos recentes (7d): densidade de focos → peso 0.15
    3. Focos mensais (30d): tendência → peso 0.10
    4. Intensidade (FRP): severidade → peso 0.10
    5. PSE calculado: dias sem chuva/precipitação → peso 0.05
    """
    if data_referencia is None:
        data_referencia = df_focos["data_hora_gmt"].max()

    focos_mun = df_focos[df_focos["municipio"].str.upper() == municipio.upper()]

    if focos_mun.empty:
        return {
            "municipio": municipio,
            "data_referencia": data_referencia,
            "focos_7d": 0,
            "focos_30d": 0,
            "focos_total_ano": 0,
            "frp_medio": None,
            "frp_max": None,
            "rf_inpe_medio": None,
            "rf_inpe_max": None,
            "rf_inpe_classe": "Mínimo",
            "dias_sem_chuva": None,
            "precipitacao_media": None,
            "pse_estimado": None,
            "F_parcial": 0,
            "metodo": "INPE_v11",
            "nota": "Sem focos registrados — risco mínimo",
        }

    dt7 = data_referencia - timedelta(days=7)
    dt30 = data_referencia - timedelta(days=30)

    mask_ate_ref = focos_mun["data_hora_gmt"] <= data_referencia
    focos_7d = focos_mun[mask_ate_ref & (focos_mun["data_hora_gmt"] >= dt7)]
    focos_30d = focos_mun[mask_ate_ref & (focos_mun["data_hora_gmt"] >= dt30)]

    n_7d = len(focos_7d)
    n_30d = len(focos_30d)

    frp_valido = focos_30d["frp"].dropna()
    frp_medio = frp_valido.mean() if not frp_valido.empty else None
    frp_max = frp_valido.max() if not frp_valido.empty else None

    rf_col = focos_30d["risco_fogo"].dropna() if "risco_fogo" in focos_30d.columns else pd.Series(dtype=float)
    rf_inpe_medio = rf_col.mean() if not rf_col.empty else None
    rf_inpe_max = rf_col.max() if not rf_col.empty else None

    dsc_col = focos_30d["numero_dias_sem_chuva"].dropna() if "numero_dias_sem_chuva" in focos_30d.columns else pd.Series(dtype=float)
    dsc_medio = dsc_col.mean() if not dsc_col.empty else None

    prec_col = focos_30d["precipitacao"].dropna() if "precipitacao" in focos_30d.columns else pd.Series(dtype=float)
    prec_media = prec_col.mean() if not prec_col.empty else None

    pse = _calcular_pse(dsc_medio or 0, prec_media or 0)

    rf_classe = classificar_rf_inpe(rf_inpe_medio) if rf_inpe_medio is not None else "Sem dados"

    return {
        "municipio": municipio,
        "data_referencia": data_referencia,
        "focos_7d": n_7d,
        "focos_30d": n_30d,
        "focos_total_ano": len(focos_mun),
        "frp_medio": round(frp_medio, 1) if frp_medio is not None else None,
        "frp_max": round(frp_max, 1) if frp_max is not None else None,
        "rf_inpe_medio": round(rf_inpe_medio, 3) if rf_inpe_medio is not None else None,
        "rf_inpe_max": round(rf_inpe_max, 3) if rf_inpe_max is not None else None,
        "rf_inpe_classe": rf_classe,
        "dias_sem_chuva": round(dsc_medio, 1) if dsc_medio is not None else None,
        "precipitacao_media": round(prec_media, 2) if prec_media is not None else None,
        "pse_estimado": round(pse, 1),
        "F7_raw": n_7d,
        "F30_raw": n_30d,
        "I_raw": frp_medio,
        "metodo": "INPE_v11",
    }


def calcular_score_fogo_normalizado(
    resultados_municipios: list[dict],
) -> pd.DataFrame:
    """
    Score de fogo baseado no método INPE v11.

    Peso principal: RF do INPE (60%)
    Suplementares: focos 7d (15%), focos 30d (10%), FRP (10%), PSE (5%)

    Escala final: 0-100.
    """
    df = pd.DataFrame(resultados_municipios)

    # RF do INPE já está em 0-1, converter para 0-100
    if "rf_inpe_medio" in df.columns and df["rf_inpe_medio"].notna().any():
        df["RF_score"] = (df["rf_inpe_medio"].fillna(0) * 100).clip(0, 100)
    else:
        df["RF_score"] = 0.0

    df["F7"] = normalizar_minmax(df["F7_raw"].astype(float)).fillna(0)
    df["F30"] = normalizar_minmax(df["F30_raw"].astype(float)).fillna(0)

    if df["I_raw"].notna().any():
        df["I"] = normalizar_minmax(df["I_raw"].astype(float)).fillna(0)
    else:
        df["I"] = 0.0

    df["PSE_score"] = normalizar_minmax(df["pse_estimado"].astype(float)).fillna(0)

    # INPE RF como base primária (60%), focos como suplemento
    df["F_parcial"] = (
        0.60 * df["RF_score"]
        + 0.15 * df["F7"]
        + 0.10 * df["F30"]
        + 0.10 * df["I"]
        + 0.05 * df["PSE_score"]
    ).fillna(0).round(1)

    return df


if __name__ == "__main__":
    import sys
    from pathlib import Path

    csv_path = Path(__file__).parent.parent / "data" / "raw" / "focos_sp_2026.csv"
    if len(sys.argv) > 1:
        csv_path = sys.argv[1]

    df = carregar_focos(str(csv_path))
    print(f"Focos carregados: {len(df)}")
    print(f"Colunas: {list(df.columns)}")
    print(f"Período: {df['data_hora_gmt'].min()} a {df['data_hora_gmt'].max()}")
    print()

    municipios = df["municipio"].unique()[:5]
    resultados = []
    for m in municipios:
        r = calcular_score_fogo_municipio(df, m)
        resultados.append(r)
        print(f"=== {m} ===")
        print(f"  RF INPE: {r['rf_inpe_medio']} ({r['rf_inpe_classe']})")
        print(f"  Focos 7d: {r['focos_7d']}, 30d: {r['focos_30d']}")
        print(f"  FRP médio: {r['frp_medio']}, PSE: {r['pse_estimado']}")
        print()

    df_norm = calcular_score_fogo_normalizado(resultados)
    print("=== Scores normalizados ===")
    print(df_norm[["municipio", "RF_score", "F7", "F30", "I", "PSE_score", "F_parcial"]].to_string(index=False))
