import pandas as pd
import numpy as np
from datetime import datetime
from scores.score_fogo import carregar_focos, calcular_score_fogo_municipio


def test_carregar_focos():
    df = carregar_focos("data/raw/focos_araraquara_2026.csv")
    assert len(df) == 57
    assert pd.api.types.is_datetime64_any_dtype(df["data_hora_gmt"])
    assert (df["frp"].dropna() >= 0).all()
    assert (df["risco_fogo"].dropna() >= 0).all()


def test_score_municipio_existente():
    df = carregar_focos("data/raw/focos_araraquara_2026.csv")
    r = calcular_score_fogo_municipio(df, "ARARAQUARA")
    assert r["focos_total_ano"] == 57
    assert r["focos_30d"] >= 0
    assert r["focos_7d"] >= 0
    assert r["focos_7d"] <= r["focos_30d"]


def test_score_municipio_inexistente():
    df = carregar_focos("data/raw/focos_araraquara_2026.csv")
    r = calcular_score_fogo_municipio(df, "INEXISTENTE")
    assert r["focos_7d"] == 0
    assert r["focos_30d"] == 0
    assert r["F_parcial"] == 0


def test_score_data_referencia_antiga():
    df = carregar_focos("data/raw/focos_araraquara_2026.csv")
    r = calcular_score_fogo_municipio(df, "ARARAQUARA", datetime(2026, 1, 1))
    assert r["focos_7d"] == 0
    assert r["focos_30d"] == 0
