import pandas as pd
from pathlib import Path
from .normalizacao import normalizar_minmax


def carregar_pivos_municipio(caminho_xlsx: str) -> pd.DataFrame:
    """Carrega planilha de área equipada de pivôs por município (ANA/Embrapa)."""
    df = pd.read_excel(caminho_xlsx, sheet_name=0, header=5)
    df.columns = [
        "mun_codigo", "mun_nome", "uf_nome", "uf_sigla", "regiao",
        "1985", "1990", "1995", "2000", "2005", "2010", "2014", "2017", "2019", "2022",
    ]
    df["mun_codigo"] = df["mun_codigo"].astype(str)
    df["mun_nome_upper"] = df["mun_nome"].str.upper().str.strip()
    df["hectares_2022"] = pd.to_numeric(df["2022"], errors="coerce").fillna(0)
    return df


def calcular_score_agricola_municipio(
    df_pivos: pd.DataFrame,
    municipio: str,
    pivos_expostos_pct: float = 0.0,
) -> dict:
    """
    Calcula dados brutos de exposição agrícola para um município.

    A = 0.50*H + 0.30*Q + 0.20*D

    - H: hectares irrigados (normalizado depois)
    - Q: quantidade de pivôs (não disponível nesta base — usamos hectares como proxy)
    - D: pivôs expostos (% próximos a focos — precisa de dados espaciais)

    pivos_expostos_pct: proporção de pivôs próximos a focos (0-1), calculada externamente
    """
    row = df_pivos[df_pivos["mun_nome_upper"] == municipio.upper()]

    if row.empty:
        return {
            "municipio": municipio,
            "hectares_irrigados": 0,
            "H_raw": 0,
            "Q_raw": 0,
            "D_raw": pivos_expostos_pct,
            "nota": "Município sem pivôs na base ANA/Embrapa",
        }

    r = row.iloc[0]
    hectares = r["hectares_2022"]

    # Estimativa de quantidade de pivôs: área média de um pivô ~120 ha (padrão Brasil)
    qtd_pivos_est = max(1, round(hectares / 120))

    return {
        "municipio": municipio,
        "mun_codigo": r["mun_codigo"],
        "uf_sigla": r["uf_sigla"],
        "hectares_irrigados": round(hectares, 1),
        "qtd_pivos_estimada": qtd_pivos_est,
        "H_raw": hectares,
        "Q_raw": qtd_pivos_est,
        "D_raw": pivos_expostos_pct * 100,
    }


def calcular_score_agricola_normalizado(
    resultados_municipios: list[dict],
) -> pd.DataFrame:
    """
    Normaliza os componentes e calcula A = 0.50*H + 0.30*Q + 0.20*D.
    """
    df = pd.DataFrame(resultados_municipios)

    df["H"] = normalizar_minmax(df["H_raw"].astype(float))
    df["Q"] = normalizar_minmax(df["Q_raw"].astype(float))
    df["D"] = df["D_raw"].astype(float).clip(0, 100)

    df["A"] = (0.50 * df["H"] + 0.30 * df["Q"] + 0.20 * df["D"]).round(1)

    return df


if __name__ == "__main__":
    base = Path(__file__).parent.parent / "data" / "raw"
    df_pivos = carregar_pivos_municipio(str(base / "pivos_area_municipio_1985_2022.xlsx"))
    print(f"Municípios com pivôs: {len(df_pivos)}")

    r = calcular_score_agricola_municipio(df_pivos, "GUAÍRA")
    print("\n=== Exposição Agrícola - Guaíra-SP ===")
    for k, v in r.items():
        print(f"  {k}: {v}")

    df_norm = calcular_score_agricola_normalizado([r])
    print(f"\n=== Score normalizado ===")
    print(df_norm[["municipio", "H", "Q", "D", "A"]].to_string(index=False))
