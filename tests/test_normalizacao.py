import pandas as pd
import pytest
from scores.normalizacao import (
    normalizar_minmax,
    normalizar_faixas,
    score_proximidade_foco,
    score_sensibilidade_ambiental,
)


def test_normalizar_minmax_basico():
    s = pd.Series([0, 25, 50, 75, 100])
    r = normalizar_minmax(s)
    assert r.min() >= 0
    assert r.max() <= 100


def test_normalizar_minmax_invertido():
    s = pd.Series([0, 25, 50, 75, 100])
    r = normalizar_minmax(s, inverter=True)
    assert r.iloc[0] > r.iloc[-1]


def test_normalizar_minmax_valores_iguais():
    s = pd.Series([5, 5, 5, 5])
    r = normalizar_minmax(s)
    assert (r == 50.0).all()


def test_normalizar_minmax_clipping():
    s = pd.Series([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 1000])
    r = normalizar_minmax(s)
    assert r.max() == 100
    assert r.min() == 0


def test_normalizar_faixas():
    s = pd.Series(range(100))
    r = normalizar_faixas(s)
    assert set(r.unique()).issubset({0, 25, 50, 75, 100})


def test_score_proximidade_foco():
    assert score_proximidade_foco(0.5) == 100
    assert score_proximidade_foco(1.0) == 100
    assert score_proximidade_foco(2.0) == 75
    assert score_proximidade_foco(4.0) == 50
    assert score_proximidade_foco(7.0) == 25
    assert score_proximidade_foco(15.0) == 0


def test_score_sensibilidade_ambiental():
    assert score_sensibilidade_ambiental(0) == 100
    assert score_sensibilidade_ambiental(-1) == 100
    assert score_sensibilidade_ambiental(3) == 75
    assert score_sensibilidade_ambiental(8) == 50
    assert score_sensibilidade_ambiental(15) == 25
    assert score_sensibilidade_ambiental(25) == 0
