import pandas as pd
from .normalizacao import normalizar_minmax


def carregar_zarc(caminho_csv: str, uf: str = None) -> pd.DataFrame:
    df = pd.read_csv(caminho_csv, sep=";", encoding="utf-8-sig", low_memory=False)
    if uf:
        return df[df["UF"] == uf]
    return df


def agregar_zarc_municipio(df: pd.DataFrame) -> pd.DataFrame:
    """
    Agrega ZARC por município gerando indicadores de aptidão agrícola.

    - taxa_aptidao: % de combinações cultura/solo/decêndio aptas (valor 20)
    - taxa_aptidao_sequeiro: idem só para sequeiro (mais sensível ao clima)
    - n_culturas_aptas: quantas culturas distintas têm ao menos 1 janela apta
    """
    dec_cols = [c for c in df.columns if c.startswith("dec")]

    def calc_taxa(g):
        total = len(g) * len(dec_cols)
        aptas = (g[dec_cols] == 20).sum().sum()
        return aptas / total * 100 if total > 0 else 0

    taxa_geral = df.groupby("municipio").apply(calc_taxa).reset_index()
    taxa_geral.columns = ["municipio", "taxa_aptidao"]

    seq = df[df["Nome_Outros_Manejos"] == "Sequeiro"]
    taxa_seq = seq.groupby("municipio").apply(calc_taxa).reset_index()
    taxa_seq.columns = ["municipio", "taxa_aptidao_sequeiro"]

    culturas = df.groupby("municipio").apply(
        lambda g: g.groupby("Nome_cultura").apply(
            lambda c: (c[dec_cols] == 20).any().any()
        ).sum()
    ).reset_index()
    culturas.columns = ["municipio", "n_culturas_aptas"]

    result = taxa_geral.merge(taxa_seq, on="municipio", how="left")
    result = result.merge(culturas, on="municipio", how="left")
    result["mun_upper"] = result["municipio"].str.upper().str.strip()
    return result


def calcular_score_zarc_normalizado(df_agg: pd.DataFrame) -> pd.DataFrame:
    """
    Score ZARC = aptidão agrícola climática.
    ZARC = 0.50*Aptidão_sequeiro + 0.30*Aptidão_geral + 0.20*Diversidade_culturas

    Score ALTO = boa aptidão (bom para plantio).
    Score BAIXO = baixa aptidão (risco climático para culturas).
    """
    df = df_agg.copy()
    df["Z_seq"] = normalizar_minmax(df["taxa_aptidao_sequeiro"]).fillna(0)
    df["Z_geral"] = normalizar_minmax(df["taxa_aptidao"]).fillna(0)
    df["Z_culturas"] = normalizar_minmax(df["n_culturas_aptas"].astype(float)).fillna(0)

    df["ZARC"] = (0.50 * df["Z_seq"] + 0.30 * df["Z_geral"] + 0.20 * df["Z_culturas"]).round(1)
    return df


def get_zarc_municipio(df_norm: pd.DataFrame, municipio: str) -> dict:
    row = df_norm[df_norm["mun_upper"] == municipio.upper()]
    if row.empty:
        return {"ZARC": None, "taxa_aptidao": None, "taxa_aptidao_sequeiro": None,
                "n_culturas_aptas": None, "tem_zarc": False}
    r = row.iloc[0]
    return {
        "ZARC": float(r["ZARC"]),
        "taxa_aptidao": round(float(r["taxa_aptidao"]), 1),
        "taxa_aptidao_sequeiro": round(float(r["taxa_aptidao_sequeiro"]), 1),
        "n_culturas_aptas": int(r["n_culturas_aptas"]),
        "tem_zarc": True,
    }
