"""Resume cinco bases do PySUS para todos os municípios de uma UF."""
import argparse, json
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
import pysus

def frame(x):
    if isinstance(x, pd.DataFrame): return x
    if hasattr(x, "to_dataframe"): return x.to_dataframe()
    y = x.df if hasattr(x, "df") else None
    return y() if callable(y) else y
def col(df, names):
    cols={str(c).upper():c for c in df.columns}
    for n in names:
        if n in cols:return cols[n]
    raise RuntimeError("coluna ausente")
def codes(s): return s.astype(str).str.replace(r"\.0$","",regex=True).str.strip().str[:6]
def recent_months():
    n=datetime.now(timezone.utc); y,m=n.year,n.month-1
    if m==0:y,m=y-1,12
    for _ in range(18):
        yield y,m; m-=1
        if m==0:y,m=y-1,12
def monthly(fn, uf, group, city_cols, value=None):
    for y,m in recent_months():
        try:
            df=frame(fn(state=uf,year=y,month=m,group=group,as_dataframe=True,show_progress=False))
            if df is None or df.empty:continue
            key=codes(df[col(df,city_cols)]); valid=key.str.len()==6
            if value:
                val=pd.to_numeric(df[col(df,[value])],errors="coerce").fillna(0)
                out=val[valid].groupby(key[valid]).sum()
            else: out=key[valid].value_counts()
            if len(out):return {str(k):int(v) for k,v in out.items()},f"{y}-{m:02d}"
        except Exception:continue
    return {},None
def annual(fn, uf, group, city_cols):
    for y in range(datetime.now(timezone.utc).year-1,datetime.now(timezone.utc).year-6,-1):
        try:
            df=frame(fn(state=uf,year=y,group=group,as_dataframe=True,show_progress=False))
            if df is None or df.empty:continue
            key=codes(df[col(df,city_cols)]); out=key[key.str.len()==6].value_counts()
            if len(out):return {str(k):int(v) for k,v in out.items()},str(y)
        except Exception:continue
    return {},None
def main():
    p=argparse.ArgumentParser();p.add_argument("--state",required=True);uf=p.parse_args().state.upper()
    cnes,cnes_p=monthly(pysus.ftp.cnes,uf,"ST",["CODUFMUN","CO_MUNICIP"])
    sih,sih_p=monthly(pysus.ftp.sih,uf,"RD",["MUNIC_RES","MUNIC_MOV"])
    sim,sim_p=annual(pysus.ftp.sim,uf,"DO",["CODMUNRES","MUN_RES"])
    nasc,nasc_p=annual(pysus.ftp.sinasc,uf,"DN",["CODMUNRES","MUN_RES"])
    sia,sia_p=monthly(pysus.ftp.sia,uf,"PA",["PA_UFMUN","UFMUN"],"PA_QTDAPR")
    all_codes=set(cnes)|set(sih)|set(sim)|set(nasc)|set(sia)
    municipios={code:{"cnes":cnes.get(code),"internacoes":sih.get(code),"mortalidade":sim.get(code),
      "nascimentos":nasc.get(code),"ambulatorial":sia.get(code)} for code in sorted(all_codes)}
    data={"uf":uf,"atualizado_em":datetime.now(timezone.utc).isoformat(timespec="seconds"),
      "competencias":{"cnes":cnes_p,"internacoes":sih_p,"mortalidade":sim_p,"nascimentos":nasc_p,"ambulatorial":sia_p},
      "municipios":municipios}
    out=Path("generated")/f"{uf}.json";out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(data,ensure_ascii=False,separators=(",",":")),encoding="utf-8")
if __name__=="__main__":main()
