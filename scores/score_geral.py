import pandas as pd
from dataclasses import dataclass, field, asdict
from typing import Optional


def classificar_risco(score: float) -> tuple[str, str]:
    """Retorna (classe, cor) para o score."""
    if score <= 20:
        return "Muito baixo", "Verde escuro"
    elif score <= 40:
        return "Baixo", "Verde claro"
    elif score <= 60:
        return "Moderado", "Amarelo"
    elif score <= 80:
        return "Alto", "Laranja"
    else:
        return "Crítico", "Vermelho"


def classificar_aptidao(score: float) -> tuple[str, str]:
    if score >= 80:
        return "Excelente", "Verde escuro"
    elif score >= 60:
        return "Boa", "Verde claro"
    elif score >= 40:
        return "Moderada", "Amarelo"
    elif score >= 20:
        return "Baixa", "Laranja"
    else:
        return "Muito baixa", "Vermelho"


def calcular_score_geral(
    F: float,
    C: float,
    A: float,
    S: Optional[float] = None,
) -> dict:
    """
    Calcula R (score geral) e P (prioridade agrícola).
    Método INPE v11 como base primária.

    F (fogo/INPE) tem peso dominante: 0.55
    C (clima): 0.20 — suplementar
    A (agrícola): 0.15 — suplementar
    S (ambiental): 0.10 — suplementar
    """
    componentes = {"F": (F, 0.55), "C": (C, 0.20), "A": (A, 0.15)}
    if S is not None:
        componentes["S"] = (S, 0.10)

    # Remover componentes sem dados (valor None passado como 0 mas flag indica ausência)
    # Por enquanto: C=0 sem dados climáticos é "ausente", A=0 sem pivôs é "ausente"
    ativos = {k: v for k, v in componentes.items() if v[0] is not None}
    peso_total = sum(v[1] for v in ativos.values())

    if peso_total > 0:
        R = sum((v[0] * v[1] / peso_total) for v in ativos.values())
    else:
        R = 0

    formula_usada = "pesos_redistribuidos" if len(ativos) < len(componentes) else "completa"

    R = round(R, 1)
    A_for_priority = A if A is not None else 0
    P = round(0.70 * R + 0.30 * A_for_priority, 1)
    classe, cor = classificar_risco(R)
    classe_p, cor_p = classificar_risco(P)

    return {
        "score_geral": R,
        "classe_risco": classe,
        "cor_risco": cor,
        "score_prioridade": P,
        "classe_prioridade": classe_p,
        "cor_prioridade": cor_p,
        "formula_usada": formula_usada,
    }


def gerar_relatorio_municipio(
    municipio: str,
    uf: str,
    dados_fogo: dict,
    dados_agricola: dict,
    dados_climatico: Optional[dict] = None,
    dados_ambiental: Optional[dict] = None,
    dados_zarc: Optional[dict] = None,
) -> dict:
    """
    Gera relatório completo para um município, com todos os sub-scores
    e fatores brutos para que a IA explique ao cliente.
    """
    F = dados_fogo.get("F_parcial", 0)

    # None = dado ausente (redistribuir peso), 0 = dado real zerado
    A = dados_agricola.get("A") if dados_agricola.get("hectares_irrigados", 0) > 0 else None
    C = dados_climatico.get("C") if dados_climatico else None
    S = dados_ambiental.get("S") if dados_ambiental else None

    geral = calcular_score_geral(F, C, A, S)

    fatores_risco = []
    rf_classe = dados_fogo.get("rf_inpe_classe")
    if rf_classe and rf_classe not in ("Mínimo", "Sem dados"):
        rf_val = dados_fogo.get("rf_inpe_medio")
        fatores_risco.append(f"Risco de fogo INPE: {rf_classe} ({rf_val:.3f})" if rf_val else f"Risco de fogo INPE: {rf_classe}")
    if dados_fogo.get("dias_sem_chuva") and dados_fogo["dias_sem_chuva"] > 10:
        fatores_risco.append(f"{dados_fogo['dias_sem_chuva']:.0f} dias sem chuva (PSE ≈ {dados_fogo.get('pse_estimado', 0):.0f})")
    if dados_fogo.get("focos_7d", 0) > 0:
        fatores_risco.append(f"{dados_fogo['focos_7d']} focos de calor nos últimos 7 dias")
    if dados_fogo.get("focos_30d", 0) > 5:
        fatores_risco.append(f"{dados_fogo['focos_30d']} focos nos últimos 30 dias")
    if dados_fogo.get("frp_max") and dados_fogo["frp_max"] > 50:
        fatores_risco.append(f"FRP máximo de {dados_fogo['frp_max']} MW (intensidade elevada)")
    if dados_agricola.get("hectares_irrigados", 0) > 5000:
        fatores_risco.append(f"{dados_agricola['hectares_irrigados']:.0f} ha irrigados expostos")
    if dados_agricola.get("qtd_pivos_estimada", 0) > 50:
        fatores_risco.append(f"~{dados_agricola['qtd_pivos_estimada']} pivôs centrais na região")
    if dados_climatico and dados_climatico.get("dias_sem_chuva", 0) and dados_climatico["dias_sem_chuva"] > 10:
        fatores_risco.append(f"{dados_climatico['dias_sem_chuva']:.0f} dias sem chuva")
    sisser = dados_agricola.get("sisser", {})
    if sisser.get("tem_seguro"):
        fatores_risco.append(f"{sisser['apolices']} apólices de seguro rural ({sisser['area_segurada_ha']:.0f} ha segurados)")
        if sisser.get("valor_segurado", 0) > 1_000_000:
            fatores_risco.append(f"R$ {sisser['valor_segurado']:,.0f} em valor segurado")

    # Score de aptidão agrícola (ZARC) — tema separado do risco
    zarc_info = dados_zarc or {}
    aptidao = None
    fatores_aptidao = []
    if zarc_info.get("tem_zarc"):
        aptidao = zarc_info["ZARC"]
        fatores_aptidao.append(f"Taxa de aptidão geral: {zarc_info['taxa_aptidao']}%")
        fatores_aptidao.append(f"Taxa de aptidão sequeiro: {zarc_info['taxa_aptidao_sequeiro']}%")
        fatores_aptidao.append(f"{zarc_info['n_culturas_aptas']} culturas com janela de plantio viável")

    relatorio = {
        "municipio": municipio,
        "uf": uf,

        # Score geral
        **geral,

        # Sub-scores para a IA explicar
        "indices": {
            "fogo": {
                "score_F": round(F, 1),
                "metodo": dados_fogo.get("metodo", "INPE_v11"),
                "rf_inpe_medio": dados_fogo.get("rf_inpe_medio"),
                "rf_inpe_max": dados_fogo.get("rf_inpe_max"),
                "rf_inpe_classe": dados_fogo.get("rf_inpe_classe"),
                "focos_7d": dados_fogo.get("focos_7d", 0),
                "focos_30d": dados_fogo.get("focos_30d", 0),
                "focos_total_ano": dados_fogo.get("focos_total_ano", 0),
                "frp_medio": dados_fogo.get("frp_medio"),
                "frp_max": dados_fogo.get("frp_max"),
                "dias_sem_chuva": dados_fogo.get("dias_sem_chuva"),
                "pse_estimado": dados_fogo.get("pse_estimado"),
            },
            "climatico": {
                "score_C": round(C, 1),
                **(dados_climatico or {"nota": "Dados climáticos pendentes"}),
            },
            "agricola": {
                "score_A": round(A, 1) if A is not None else 0,
                "hectares_irrigados": dados_agricola.get("hectares_irrigados", 0),
                "qtd_pivos_estimada": dados_agricola.get("qtd_pivos_estimada", 0),
                "sisser": dados_agricola.get("sisser", {}),
            },
            "ambiental": {
                "score_S": round(S, 1) if S is not None else None,
                **(dados_ambiental or {"nota": "Dados ambientais pendentes"}),
            },
        },

        # Fatores humanos para explicação
        "fatores_risco": fatores_risco,

        # Score de Aptidão Agrícola (tema separado)
        "aptidao": {
            "score_aptidao": round(aptidao, 1) if aptidao is not None else None,
            "classe_aptidao": classificar_aptidao(aptidao) if aptidao is not None else None,
            "zarc": zarc_info if zarc_info.get("tem_zarc") else None,
            "fatores_aptidao": fatores_aptidao,
        },

        # Metadados
        "data_referencia": str(dados_fogo.get("data_referencia", "")),
        "fontes": ["INPE/Queimadas (Método Risco de Fogo v11)", "ANA/Embrapa Pivôs Centrais", "MAPA/ZARC"],
    }

    return relatorio


def formatar_relatorio_texto(rel: dict) -> str:
    """Formata relatório para exibição em texto."""
    linhas = [
        f"{'='*50}",
        f"Município: {rel['municipio']} – {rel['uf']}",
        f"Score geral: {rel['score_geral']}/100",
        f"Classificação: {rel['classe_risco']}",
        f"Prioridade agrícola: {rel['score_prioridade']}/100 ({rel['classe_prioridade']})",
        f"{'='*50}",
        "",
        f"Fogo (F):     {rel['indices']['fogo']['score_F']:.0f}",
        f"Clima (C):    {rel['indices']['climatico']['score_C']:.0f}",
        f"Agrícola (A): {rel['indices']['agricola']['score_A']:.0f}",
    ]

    s_val = rel['indices']['ambiental']['score_S']
    if s_val is not None:
        linhas.append(f"Ambiental (S): {s_val:.0f}")

    linhas.append("")
    linhas.append("Principais fatores:")
    for f in rel["fatores_risco"]:
        linhas.append(f"  • {f}")

    linhas.append("")
    linhas.append(f"Data de referência: {rel['data_referencia']}")
    linhas.append(f"Fontes: {', '.join(rel['fontes'])}")

    return "\n".join(linhas)


if __name__ == "__main__":
    # Teste com dados simulados de Guaíra
    dados_fogo = {
        "F_parcial": 65.0,
        "focos_7d": 52,
        "focos_30d": 52,
        "focos_total_ano": 165,
        "frp_medio": 37.1,
        "frp_max": 129.4,
        "data_referencia": "2026-09-29",
    }
    dados_agricola = {
        "A": 40.0,
        "hectares_irrigados": 16315,
        "qtd_pivos_estimada": 136,
    }

    rel = gerar_relatorio_municipio("Guaíra", "SP", dados_fogo, dados_agricola)
    print(formatar_relatorio_texto(rel))
    print()
    print("--- JSON dos índices (para IA) ---")
    import json
    print(json.dumps(rel["indices"], indent=2, ensure_ascii=False))
