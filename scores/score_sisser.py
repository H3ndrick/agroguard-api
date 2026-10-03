import pandas as pd
from .normalizacao import normalizar_minmax


def carregar_sisser(caminho_csv: str) -> pd.DataFrame:
    df = pd.read_csv(caminho_csv, sep=";", encoding="latin-1", low_memory=False)
    for col in ["NR_AREA_TOTAL", "VL_LIMITE_GARANTIA", "VL_SUBVENCAO_FEDERAL", "VL_PREMIO_LIQUIDO"]:
        df[col] = pd.to_numeric(df[col].astype(str).str.replace(",", "."), errors="coerce")
    df["mun_upper"] = df["NM_MUNICIPIO_PROPRIEDADE"].str.upper().str.strip()
    return df


def agregar_sisser_municipio(df: pd.DataFrame, uf: str = "GO") -> pd.DataFrame:
    """Agrega dados do SISSER por município."""
    filtro = df[df["SG_UF_PROPRIEDADE"] == uf]
    return filtro.groupby("mun_upper").agg(
        apolices=("NR_PROPOSTA", "count"),
        area_segurada_ha=("NR_AREA_TOTAL", "sum"),
        valor_segurado=("VL_LIMITE_GARANTIA", "sum"),
        culturas_distintas=("NM_CULTURA_GLOBAL", "nunique"),
    ).reset_index()


def calcular_score_sisser_normalizado(df_agg: pd.DataFrame) -> pd.DataFrame:
    """
    Score SISSER = exposição econômica agrícola.
    SIS = 0.40*Area + 0.35*Valor + 0.25*Apolices

    Mais área/valor/apólices = mais exposição = score maior.
    """
    df = df_agg.copy()
    df["S_area"] = normalizar_minmax(df["area_segurada_ha"]).fillna(0)
    df["S_valor"] = normalizar_minmax(df["valor_segurado"]).fillna(0)
    df["S_apolices"] = normalizar_minmax(df["apolices"].astype(float)).fillna(0)

    df["SIS"] = (0.40 * df["S_area"] + 0.35 * df["S_valor"] + 0.25 * df["S_apolices"]).round(1)
    return df


def get_sisser_municipio(df_norm: pd.DataFrame, municipio: str) -> dict:
    row = df_norm[df_norm["mun_upper"] == municipio.upper()]
    if row.empty:
        return {
            "SIS": 0,
            "area_segurada_ha": 0,
            "valor_segurado": 0,
            "apolices": 0,
            "culturas_distintas": 0,
            "tem_seguro": False,
        }
    r = row.iloc[0]
    return {
        "SIS": float(r["SIS"]),
        "area_segurada_ha": round(float(r["area_segurada_ha"]), 1),
        "valor_segurado": round(float(r["valor_segurado"]), 2),
        "apolices": int(r["apolices"]),
        "culturas_distintas": int(r["culturas_distintas"]),
        "tem_seguro": True,
    }
