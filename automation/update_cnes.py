"""Gera um resumo público do CNES para o piloto Inov@Rede Saúde 360."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pysus


MUNICIPIO_IBGE = "313820"
MUNICIPIO_NOME = "Lavras"
UF = "MG"
OUTPUT = Path.cwd() / "data" / "cnes-lavras.json"


def month_candidates(limit: int = 18):
    now = datetime.now(timezone.utc)
    year, month = now.year, now.month - 1
    if month == 0:
        year, month = year - 1, 12
    for _ in range(limit):
        yield year, month
        month -= 1
        if month == 0:
            year, month = year - 1, 12


def find_column(columns, candidates):
    normalized = {str(column).upper(): column for column in columns}
    for candidate in candidates:
        if candidate in normalized:
            return normalized[candidate]
    return None


def clean(value):
    if pd.isna(value):
        return ""
    return str(value).strip()


def load_latest():
    errors = []
    for year, month in month_candidates():
        try:
            frame = pysus.ftp.cnes(
                state=UF,
                year=year,
                month=month,
                group="ST",
                as_dataframe=True,
                show_progress=False,
            )
            if not isinstance(frame, pd.DataFrame):
                if hasattr(frame, "to_dataframe"):
                    frame = frame.to_dataframe()
                elif hasattr(frame, "df"):
                    frame = frame.df
            if not isinstance(frame, pd.DataFrame) or frame.empty:
                raise RuntimeError("arquivo sem registros")
            return frame, year, month
        except Exception as exc:  # tenta o mês anterior
            errors.append(f"{year}-{month:02d}: {exc}")
    raise RuntimeError("Nenhum mês recente do CNES pôde ser processado. " + " | ".join(errors[-3:]))


def main():
    frame, year, month = load_latest()
    city_column = find_column(
        frame.columns,
        ["CO_MUNICIP", "CO_MUNICIPIO", "CO_MUNICIPIO_GESTOR", "MUNIC_RES"],
    )
    if city_column is None:
        raise RuntimeError("A coluna de município não foi encontrada no arquivo CNES.")

    codes = (
        frame[city_column]
        .astype(str)
        .str.replace(r"\.0$", "", regex=True)
        .str.strip()
        .str[:6]
    )
    city = frame.loc[codes == MUNICIPIO_IBGE].copy()
    if city.empty:
        raise RuntimeError("Nenhum estabelecimento de Lavras foi localizado.")

    cnes_column = find_column(city.columns, ["CNES", "CO_CNES", "CO_UNIDADE"])
    name_column = find_column(city.columns, ["NO_FANTASIA", "NOME_FANTASIA", "NO_RAZAO_SOCIAL"])
    type_column = find_column(city.columns, ["TP_UNID_ID", "CO_TIPO_UNIDADE", "TP_UNIDADE"])
    management_column = find_column(city.columns, ["TP_GESTAO", "TP_GESTOR"])

    if cnes_column:
        city = city.drop_duplicates(subset=[cnes_column])

    management = {}
    if management_column:
        management = {
            clean(key) or "Não informado": int(value)
            for key, value in city[management_column].fillna("").value_counts().items()
        }

    establishments = []
    for _, row in city.head(20).iterrows():
        establishments.append(
            {
                "cnes": clean(row[cnes_column]) if cnes_column else "",
                "nome": clean(row[name_column]) if name_column else "Estabelecimento sem nome",
                "tipo": clean(row[type_column]) if type_column else "",
            }
        )

    payload = {
        "status": "ok",
        "fonte": "CNES/DATASUS via PySUS",
        "municipio": MUNICIPIO_NOME,
        "uf": UF,
        "codigo_ibge": "3138203",
        "competencia": f"{year}-{month:02d}",
        "atualizado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "total_estabelecimentos": int(len(city)),
        "gestao": management,
        "amostra_estabelecimentos": establishments,
        "observacao": "Contagem piloto baseada no arquivo de estabelecimentos (grupo ST) do CNES.",
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
