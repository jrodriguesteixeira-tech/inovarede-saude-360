"""Gera indicadores públicos resumidos de Lavras a partir do PySUS."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pysus


UF = "MG"
MUNICIPIO = "Lavras"
CODIGO_6 = "313820"
CODIGO_7 = "3138203"
OUTPUT = Path.cwd() / "data" / "indicadores-lavras.json"


def as_frame(value):
    if isinstance(value, pd.DataFrame):
        return value
    if hasattr(value, "to_dataframe"):
        return value.to_dataframe()
    if hasattr(value, "df"):
        result = value.df
        return result() if callable(result) else result
    raise RuntimeError("O PySUS não retornou uma tabela.")


def find_column(frame, candidates):
    normalized = {str(column).upper(): column for column in frame.columns}
    for candidate in candidates:
        if candidate in normalized:
            return normalized[candidate]
    raise RuntimeError("Coluna municipal não encontrada: " + ", ".join(map(str, frame.columns)))


def city_rows(frame, candidates):
    column = find_column(frame, candidates)
    codes = (
        frame[column]
        .astype(str)
        .str.replace(r"\.0$", "", regex=True)
        .str.strip()
        .str[:6]
    )
    return frame.loc[codes == CODIGO_6].copy()


def months(limit=18):
    now = datetime.now(timezone.utc)
    year, month = now.year, now.month - 1
    if month == 0:
        year, month = year - 1, 12
    for _ in range(limit):
        yield year, month
        month -= 1
        if month == 0:
            year, month = year - 1, 12


def years(limit=5):
    current = datetime.now(timezone.utc).year - 1
    for offset in range(limit):
        yield current - offset


def monthly_indicator(fetcher, group, city_columns, value_column=None):
    errors = []
    for year, month in months():
        try:
            frame = as_frame(
                fetcher(
                    state=UF,
                    year=year,
                    month=month,
                    group=group,
                    as_dataframe=True,
                    show_progress=False,
                )
            )
            filtered = city_rows(frame, city_columns)
            if filtered.empty:
                raise RuntimeError("Competência sem registros do município.")
            if value_column:
                column = find_column(filtered, [value_column])
                value = pd.to_numeric(filtered[column], errors="coerce").fillna(0).sum()
            else:
                value = len(filtered)
            return {"valor": int(value), "competencia": f"{year}-{month:02d}", "status": "ok"}
        except Exception as exc:
            errors.append(str(exc))
    return {"valor": None, "competencia": None, "status": "indisponivel", "erro": errors[-1] if errors else ""}


def annual_indicator(fetcher, group, city_columns):
    errors = []
    for year in years():
        try:
            frame = as_frame(
                fetcher(
                    state=UF,
                    year=year,
                    group=group,
                    as_dataframe=True,
                    show_progress=False,
                )
            )
            filtered = city_rows(frame, city_columns)
            if filtered.empty:
                raise RuntimeError("Ano sem registros do município.")
            return {"valor": int(len(filtered)), "competencia": str(year), "status": "ok"}
        except Exception as exc:
            errors.append(str(exc))
    return {"valor": None, "competencia": None, "status": "indisponivel", "erro": errors[-1] if errors else ""}


def main():
    indicators = {
        "internacoes": {
            **monthly_indicator(
                pysus.ftp.sih,
                "RD",
                ["MUNIC_RES", "MUNIC_MOV", "MUNICIPIO_RESIDENCIA"],
            ),
            "nome": "Internações hospitalares",
            "fonte": "SIH/SUS",
            "unidade": "internações",
            "criterio": "Município de residência",
        },
        "mortalidade": {
            **annual_indicator(
                pysus.ftp.sim,
                "DO",
                ["CODMUNRES", "CODMUNRESID", "MUN_RES"],
            ),
            "nome": "Óbitos registrados",
            "fonte": "SIM",
            "unidade": "óbitos",
            "criterio": "Município de residência",
        },
        "nascimentos": {
            **annual_indicator(
                pysus.ftp.sinasc,
                "DN",
                ["CODMUNRES", "CODMUNRESID", "MUN_RES"],
            ),
            "nome": "Nascidos vivos",
            "fonte": "SINASC",
            "unidade": "nascimentos",
            "criterio": "Município de residência da mãe",
        },
        "ambulatorial": {
            **monthly_indicator(
                pysus.ftp.sia,
                "PA",
                ["PA_UFMUN", "UFMUN", "MUNICIPIO"],
                "PA_QTDAPR",
            ),
            "nome": "Produção ambulatorial aprovada",
            "fonte": "SIA/SUS",
            "unidade": "procedimentos",
            "criterio": "Município do estabelecimento",
        },
    }
    payload = {
        "status": "ok" if any(item["status"] == "ok" for item in indicators.values()) else "indisponivel",
        "municipio": MUNICIPIO,
        "uf": UF,
        "codigo_ibge": CODIGO_7,
        "atualizado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "indicadores": indicators,
        "nota": "Dados preliminares sujeitos às revisões e competências disponibilizadas pelo DATASUS.",
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
