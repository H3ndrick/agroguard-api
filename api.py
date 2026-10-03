from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import geopandas as gpd
import pandas as pd
import json
from shapely.geometry import Point
from pathlib import Path

from scores.score_fogo import carregar_focos, calcular_score_fogo_municipio, calcular_score_fogo_normalizado
from scores.score_agricola import carregar_pivos_municipio, calcular_score_agricola_municipio, calcular_score_agricola_normalizado
from scores.score_climatico import calcular_score_climatico_municipio, calcular_score_climatico_normalizado
from scores.score_sisser import carregar_sisser, agregar_sisser_municipio, calcular_score_sisser_normalizado, get_sisser_municipio
from scores.score_zarc import carregar_zarc, agregar_zarc_municipio, calcular_score_zarc_normalizado, get_zarc_municipio
from scores.score_geral import gerar_relatorio_municipio
import math
import numpy as np
from threading import Lock


def sanitize(obj):
    """Replace NaN/inf with None for JSON serialization."""
    if isinstance(obj, dict):
        return {k: sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sanitize(v) for v in obj]
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if isinstance(obj, (np.floating, np.integer)):
        v = float(obj)
        return None if math.isnan(v) or math.isinf(v) else v
    return obj

DATA_DIR = Path(__file__).parent / "data" / "raw"

UF_CODIGOS = {
    'AC':'12','AL':'27','AM':'13','AP':'16','BA':'29','CE':'23','DF':'53',
    'ES':'32','GO':'52','MA':'21','MG':'31','MS':'50','MT':'51','PA':'15',
    'PB':'25','PE':'26','PI':'22','PR':'41','RJ':'33','RN':'24','RO':'11',
    'RR':'14','RS':'43','SC':'42','SE':'28','SP':'35','TO':'17',
}

UF_CENTRO = {
    'AC':(-9.0,-70.8),'AL':(-9.5,-36.6),'AM':(-3.4,-65.0),'AP':(1.4,-51.8),
    'BA':(-12.6,-41.7),'CE':(-5.5,-39.3),'DF':(-15.8,-47.9),'ES':(-19.6,-40.5),
    'GO':(-15.5,-49.5),'MA':(-5.1,-44.3),'MG':(-18.5,-44.3),'MS':(-20.8,-54.8),
    'MT':(-12.7,-56.1),'PA':(-3.5,-52.0),'PB':(-7.1,-36.8),'PE':(-8.3,-37.9),
    'PI':(-7.7,-42.7),'PR':(-24.6,-51.3),'RJ':(-22.5,-43.2),'RN':(-5.8,-36.6),
    'RO':(-10.9,-62.8),'RR':(2.1,-61.0),'RS':(-29.8,-53.6),'SC':(-27.6,-50.4),
    'SE':(-10.6,-37.4),'SP':(-22.3,-49.1),'TO':(-10.2,-48.3),
}

_global = {}
_cache = {}
_cache_locks = {}
_cache_locks_guard = Lock()

def load_global():
    print("Carregando malha municipal BR...")
    gdf = gpd.read_file(str(DATA_DIR / "municipios_br.json"))
    nomes = pd.read_csv(str(DATA_DIR / "municipios_br_nomes.csv"), dtype={"codigo": str})
    gdf["codarea"] = gdf["codarea"].astype(str)
    nomes["codigo"] = nomes["codigo"].astype(str)
    gdf = gdf.merge(nomes, left_on="codarea", right_on="codigo", how="left")
    _global["municipios_gdf"] = gdf

    print("Carregando focos BR...")
    focos_list = []
    for arq in ["focos_br_2025.csv", "focos_br_2026.csv"]:
        caminho = DATA_DIR / arq
        if caminho.exists():
            df_f = carregar_focos(str(caminho))
            focos_list.append(df_f)
            print(f"  {arq}: {len(df_f)} focos")
    _global["focos"] = pd.concat(focos_list, ignore_index=True) if focos_list else pd.DataFrame()
    print(f"  Total: {len(_global['focos'])} focos carregados")

    print("Carregando pivôs...")
    _global["pivos"] = carregar_pivos_municipio(str(DATA_DIR / "pivos_area_municipio_1985_2022.xlsx"))

    print("Carregando SISSER...")
    _global["sisser"] = carregar_sisser(str(DATA_DIR / "sisser_psr_2025.csv"))

    print("Carregando ZARC...")
    _global["zarc"] = carregar_zarc(str(DATA_DIR / "zarc_2024_2025.csv"), uf=None)

    # Pré-calcular contornos por UF (dissolve é lento, fazer uma vez)
    print("Pré-calculando contornos por UF...")
    gdf["uf_code"] = gdf["codarea"].str[:2]
    _global["contornos"] = {}
    for uf_code, uf_sigla in {v: k for k, v in UF_CODIGOS.items()}.items():
        uf_gdf = gdf[gdf["uf_code"] == uf_code]
        if not uf_gdf.empty:
            contorno = uf_gdf.dissolve().geometry.iloc[0].__geo_interface__
            _global["contornos"][uf_sigla] = {
                "type": "FeatureCollection",
                "features": [{"type": "Feature", "geometry": contorno, "properties": {"uf": uf_sigla}}]
            }

    print(f"Dados globais prontos: {len(gdf)} municípios, {len(_global['contornos'])} contornos")

def get_cache_lock(uf: str) -> Lock:
    with _cache_locks_guard:
        if uf not in _cache_locks:
            _cache_locks[uf] = Lock()

        return _cache_locks[uf]

def load_estado(uf: str) -> dict:
    uf = uf.upper()

    if uf in _cache:
        return _cache[uf]

    lock = get_cache_lock(uf)

    with lock:
        # Outra requisição pode ter concluído enquanto esta aguardava o lock.
        if uf in _cache:
            return _cache[uf]

        print(f"Calculando scores para {uf}...", flush=True)

        codigo = UF_CODIGOS.get(uf, "")

        if not codigo:
            raise ValueError(f"UF inválida: {uf}")

        gdf = _global["municipios_gdf"]
        gdf_uf = gdf[gdf["codarea"].str.startswith(codigo)].copy()

        focos = _global["focos"]

        estado_nome_map = {
            'AC': 'ACRE',
            'AL': 'ALAGOAS',
            'AM': 'AMAZONAS',
            'AP': 'AMAPÁ',
            'BA': 'BAHIA',
            'CE': 'CEARÁ',
            'DF': 'DISTRITO FEDERAL',
            'ES': 'ESPÍRITO SANTO',
            'GO': 'GOIÁS',
            'MA': 'MARANHÃO',
            'MG': 'MINAS GERAIS',
            'MS': 'MATO GROSSO DO SUL',
            'MT': 'MATO GROSSO',
            'PA': 'PARÁ',
            'PB': 'PARAÍBA',
            'PE': 'PERNAMBUCO',
            'PI': 'PIAUÍ',
            'PR': 'PARANÁ',
            'RJ': 'RIO DE JANEIRO',
            'RN': 'RIO GRANDE DO NORTE',
            'RO': 'RONDÔNIA',
            'RR': 'RORAIMA',
            'RS': 'RIO GRANDE DO SUL',
            'SC': 'SANTA CATARINA',
            'SE': 'SERGIPE',
            'SP': 'SÃO PAULO',
            'TO': 'TOCANTINS',
        }

        estado_nome = estado_nome_map.get(uf, uf)
        focos_uf = focos[focos["estado"] == estado_nome].copy()

        print(f"  [{uf}] calculando scores de fogo...", flush=True)

        municipios_com_focos = focos_uf["municipio"].dropna().unique()

        resultados_fogo = [
            calcular_score_fogo_municipio(focos_uf, municipio)
            for municipio in municipios_com_focos
        ]

        scores_fogo = (
            calcular_score_fogo_normalizado(resultados_fogo)
            if resultados_fogo
            else pd.DataFrame()
        )

        print(f"  [{uf}] calculando scores climáticos...", flush=True)

        resultados_clima = [
            calcular_score_climatico_municipio(focos_uf, municipio)
            for municipio in municipios_com_focos
        ]

        resultados_clima = [
            resultado
            for resultado in resultados_clima
            if resultado.get("C_disponivel")
        ]

        scores_clima = (
            calcular_score_climatico_normalizado(resultados_clima)
            if resultados_clima
            else pd.DataFrame()
        )

        print(f"  [{uf}] calculando scores agrícolas...", flush=True)

        pivos = _global["pivos"]
        pivos_uf = pivos[pivos["uf_sigla"] == uf]

        resultados_agri = [
            calcular_score_agricola_municipio(
                pivos,
                row["mun_nome_upper"],
            )
            for _, row in pivos_uf.iterrows()
        ]

        scores_agri = (
            calcular_score_agricola_normalizado(resultados_agri)
            if resultados_agri
            else pd.DataFrame()
        )

        print(f"  [{uf}] agregando SISSER...", flush=True)

        sisser_agg = agregar_sisser_municipio(_global["sisser"], uf)

        scores_sisser = (
            calcular_score_sisser_normalizado(sisser_agg)
            if not sisser_agg.empty
            else pd.DataFrame()
        )

        print(f"  [{uf}] agregando ZARC...", flush=True)

        zarc_uf = _global["zarc"][_global["zarc"]["UF"] == uf]

        if not zarc_uf.empty:
            zarc_agg = agregar_zarc_municipio(zarc_uf)
            scores_zarc = calcular_score_zarc_normalizado(zarc_agg)
        else:
            scores_zarc = pd.DataFrame()

        result = {
            "gdf": gdf_uf,
            "focos": focos_uf,
            "scores_fogo": scores_fogo,
            "scores_clima": scores_clima,
            "scores_agri": scores_agri,
            "scores_sisser": scores_sisser,
            "scores_zarc": scores_zarc,
        }

        _cache[uf] = result

        print(
            f"  {uf}: {len(gdf_uf)} mun, {len(focos_uf)} focos, "
            f"{len(scores_fogo)} fogo, {len(scores_clima)} clima, "
            f"{len(scores_agri)} agri, {len(scores_sisser)} sisser, "
            f"{len(scores_zarc)} zarc",
            flush=True,
        )

        return result

@asynccontextmanager
async def lifespan(app: FastAPI):
    load_global()
    yield


app = FastAPI(
    title="AgroGuard API",
    description="Índice de risco ambiental e prioridade agrícola para áreas irrigadas",
    version="0.3.0",
    lifespan=lifespan,
)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


def find_municipio(lat: float, lon: float, uf: str) -> dict | None:
    st = load_estado(uf)
    gdf = st["gdf"]
    point = Point(lon, lat)
    match = gdf[gdf.geometry.contains(point)]
    if match.empty:
        return None
    row = match.iloc[0]
    return {"codigo": row["codarea"], "nome": row.get("nome", "Desconhecido"), "uf": uf}


def get_dados_fogo(st: dict, nome_upper: str) -> dict:
    fogo_df = st["scores_fogo"]
    fogo_row = fogo_df[fogo_df["municipio"] == nome_upper] if not fogo_df.empty else pd.DataFrame()
    if fogo_row.empty:
        return {"F_parcial": 0, "focos_7d": 0, "focos_30d": 0, "focos_total_ano": 0,
                "frp_medio": None, "frp_max": None, "rf_inpe_medio": None,
                "rf_inpe_classe": "Mínimo", "dias_sem_chuva": None,
                "pse_estimado": None, "metodo": "INPE_v11", "data_referencia": ""}
    fr = fogo_row.iloc[0]
    return {
        "F_parcial": float(fr["F_parcial"]),
        "focos_7d": int(fr["focos_7d"]),
        "focos_30d": int(fr["focos_30d"]),
        "focos_total_ano": int(fr["focos_total_ano"]),
        "frp_medio": round(float(fr["frp_medio"]), 1) if pd.notna(fr.get("frp_medio")) else None,
        "frp_max": round(float(fr["frp_max"]), 1) if pd.notna(fr.get("frp_max")) else None,
        "rf_inpe_medio": round(float(fr["rf_inpe_medio"]), 3) if pd.notna(fr.get("rf_inpe_medio")) else None,
        "rf_inpe_max": round(float(fr["rf_inpe_max"]), 3) if pd.notna(fr.get("rf_inpe_max")) else None,
        "rf_inpe_classe": fr.get("rf_inpe_classe", "Sem dados"),
        "dias_sem_chuva": round(float(fr["dias_sem_chuva"]), 1) if pd.notna(fr.get("dias_sem_chuva")) else None,
        "pse_estimado": round(float(fr["pse_estimado"]), 1) if pd.notna(fr.get("pse_estimado")) else None,
        "metodo": fr.get("metodo", "INPE_v11"),
        "data_referencia": str(fr["data_referencia"]),
    }


def get_dados_clima(st: dict, nome_upper: str) -> dict | None:
    clima_df = st["scores_clima"]
    clima_row = clima_df[clima_df["municipio"] == nome_upper] if not clima_df.empty else pd.DataFrame()
    if clima_row.empty:
        return None
    cr = clima_row.iloc[0]
    return {
        "C": float(cr["C"]),
        "dias_sem_chuva": cr.get("dias_sem_chuva_medio"),
        "precipitacao_media": cr.get("precipitacao_media"),
        "risco_fogo_meteo": cr.get("risco_fogo_meteo"),
    }


def get_dados_agricola(st: dict, nome_upper: str) -> dict:
    agri_df = st["scores_agri"]
    agri_row = agri_df[agri_df["municipio"] == nome_upper] if not agri_df.empty else pd.DataFrame()
    if agri_row.empty:
        return {"A": 0, "hectares_irrigados": 0, "qtd_pivos_estimada": 0}
    ar = agri_row.iloc[0]
    return {
        "A": float(ar["A"]),
        "hectares_irrigados": float(ar.get("H_raw", 0)),
        "qtd_pivos_estimada": int(ar.get("Q_raw", 0)),
    }


@app.get("/score")
def get_score(lat: float, lon: float, uf: str = "GO"):
    uf = uf.upper()
    if uf not in UF_CODIGOS:
        raise HTTPException(400, f"UF inválida: {uf}")

    mun = find_municipio(lat, lon, uf)
    if not mun:
        raise HTTPException(404, f"Coordenadas fora do estado de {uf}")

    st = _cache[uf]
    nome_upper = mun["nome"].upper()
    dados_fogo = get_dados_fogo(st, nome_upper)
    dados_clima = get_dados_clima(st, nome_upper)
    dados_agricola = get_dados_agricola(st, nome_upper)

    # SISSER
    dados_sisser = get_sisser_municipio(st["scores_sisser"], nome_upper)
    dados_agricola["sisser"] = dados_sisser
    if dados_sisser["tem_seguro"] and dados_agricola.get("hectares_irrigados", 0) > 0:
        dados_agricola["A"] = round(0.6 * dados_agricola["A"] + 0.4 * dados_sisser["SIS"], 1)
    elif dados_sisser["tem_seguro"]:
        dados_agricola["A"] = dados_sisser["SIS"]
        dados_agricola["hectares_irrigados"] = dados_sisser["area_segurada_ha"]

    # ZARC
    dados_zarc = get_zarc_municipio(st["scores_zarc"], nome_upper)

    relatorio = gerar_relatorio_municipio(
        municipio=mun["nome"], uf=mun["uf"],
        dados_fogo=dados_fogo, dados_agricola=dados_agricola,
        dados_climatico=dados_clima, dados_zarc=dados_zarc,
    )
    relatorio["coordenadas"] = {"lat": lat, "lon": lon}
    return sanitize(relatorio)


@app.get("/focos/{uf}")
def get_focos_heatmap(
    uf: str,
    lat: float,
    lon: float,
    limit: int = 5000,
):
    """Retorna os focos do município que contém a coordenada consultada."""
    uf = uf.upper()

    if uf not in UF_CODIGOS:
        raise HTTPException(400, f"UF inválida: {uf}")

    municipio = find_municipio(lat, lon, uf)

    if not municipio:
        raise HTTPException(
            status_code=404,
            detail=f"Coordenadas fora do estado de {uf}",
        )

    st = load_estado(uf)
    focos_uf = st["focos"]

    if focos_uf.empty:
        return {
            "municipio": municipio["nome"],
            "total": 0,
            "pontos": [],
        }

    nome_municipio = municipio["nome"].strip().upper()

    # Padroniza os nomes para comparar "Araraquara", "ARARAQUARA"
    # e valores com espaços extras.
    municipios_focos = (
        focos_uf["municipio"]
        .fillna("")
        .astype(str)
        .str.strip()
        .str.upper()
    )

    focos_municipio = focos_uf[
        municipios_focos == nome_municipio
    ]

    if focos_municipio.empty:
        return {
            "municipio": municipio["nome"],
            "total": 0,
            "pontos": [],
        }

    sample = (
        focos_municipio[["lat", "lon", "frp"]]
        .dropna(subset=["lat", "lon"])
        .rename(columns={
            "lat": "latitude",
            "lon": "longitude",
        })
    )

    total = len(sample)

    if len(sample) > limit:
        sample = sample.sample(limit, random_state=42)

    print(
        f"[FOCOS] {uf} / {municipio['nome']}: "
        f"{total} focos; {len(sample)} enviados ao mapa",
        flush=True,
    )

    return {
        "municipio": municipio["nome"],
        "total": total,
        "pontos": sanitize(sample.to_dict(orient="records")),
    }


@app.get("/estado/{uf}")
def get_estado_info(uf: str):
    """Carrega estado e retorna info (municipios, contorno, centro)."""
    uf = uf.upper()
    if uf not in UF_CODIGOS:
        raise HTTPException(400, f"UF inválida: {uf}")

    st = load_estado(uf)
    gdf = st["gdf"]

    # Lista de municípios com centroide
    municipios = []
    for _, row in gdf.iterrows():
        c = row.geometry.centroid
        municipios.append({"nome": row.get("nome", ""), "lat": c.y, "lon": c.x})
    municipios.sort(key=lambda m: m["nome"])

    centro = UF_CENTRO.get(uf, (-14.2, -51.9))
    contorno = _global["contornos"].get(uf, {"type": "FeatureCollection", "features": []})

    return {
        "uf": uf,
        "centro": {"lat": centro[0], "lon": centro[1]},
        "municipios": municipios,
        "contorno": contorno,
        "stats": {
            "municipios": len(gdf),
            "focos": len(st["focos"]),
            "com_fogo": len(st["scores_fogo"]),
            "com_clima": len(st["scores_clima"]),
            "com_agri": len(st["scores_agri"]),
            "com_sisser": len(st["scores_sisser"]),
            "com_zarc": len(st["scores_zarc"]),
        }
    }


@app.get("/estados")
def list_estados():
    return [{"uf": uf, "centro": {"lat": c[0], "lon": c[1]}} for uf, c in sorted(UF_CENTRO.items())]


@app.get("/")
def root():
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@app.get("/health")
def health():
    return {
        "status": "ok",
        "focos_total": len(_global.get("focos", [])),
        "municipios_total": len(_global.get("municipios_gdf", [])),
        "estados_carregados": list(_cache.keys()),
    }
