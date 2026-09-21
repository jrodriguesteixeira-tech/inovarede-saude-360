"""Resume cinco bases do PySUS para todos os municípios de uma UF."""
import argparse, gc, json, multiprocessing as mp
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
def optional_col(df, names):
    cols={str(c).upper():c for c in df.columns}
    for n in names:
        if n in cols:return cols[n]
    return None
def ratios(df, city_cols, definitions):
    city=codes(df[col(df,city_cols)])
    valid_city=city.str.len()==6
    output={}
    for name, candidates, evaluate in definitions:
        field=optional_col(df,candidates)
        if field is None:continue
        series=df[field]
        valid, positive=evaluate(series)
        valid=valid & valid_city
        positive=positive & valid
        denominator=valid.groupby(city).sum()
        numerator=positive.groupby(city).sum()
        output[name]={str(code):{"n":int(numerator.get(code,0)),"d":int(total)}
                      for code,total in denominator.items() if total>0}
    return output
def recent_months():
    n=datetime.now(timezone.utc); y,m=n.year,n.month-1
    if m==0:y,m=y-1,12
    for _ in range(18):
        yield y,m; m-=1
        if m==0:y,m=y-1,12
def monthly(fn, uf, group, city_cols, value=None):
    for y,m in recent_months():
        try:
            selected=[city_cols[0]] + ([value] if value else [])
            df=frame(fn(state=uf,year=y,month=m,group=group,columns=selected,as_dataframe=True,show_progress=False))
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
            df=frame(fn(state=uf,year=y,group=group,columns=[city_cols[0]],as_dataframe=True,show_progress=False))
            if df is None or df.empty:continue
            key=codes(df[col(df,city_cols)]); out=key[key.str.len()==6].value_counts()
            if len(out):return {str(k):int(v) for k,v in out.items()},str(y)
        except Exception:continue
    return {},None

def annual_sinasc(uf):
    definitions=[
      ("prenatal_7_mais",["CONSPRENAT"],lambda s:(pd.to_numeric(s,errors="coerce").between(0,98),pd.to_numeric(s,errors="coerce")>=7)),
      ("baixo_peso",["PESO"],lambda s:(pd.to_numeric(s,errors="coerce").between(1,9998),pd.to_numeric(s,errors="coerce")<2500)),
      ("mae_adolescente",["IDADEMAE"],lambda s:(pd.to_numeric(s,errors="coerce").between(10,99),pd.to_numeric(s,errors="coerce").between(10,19))),
      ("apgar5_menor_7",["APGAR5"],lambda s:(pd.to_numeric(s,errors="coerce").between(0,10),pd.to_numeric(s,errors="coerce")<7)),
      ("anomalia_congenita",["IDANOMAL"],lambda s:(pd.to_numeric(s,errors="coerce").isin([1,2]),pd.to_numeric(s,errors="coerce")==1)),
    ]
    for y in range(datetime.now(timezone.utc).year-1,datetime.now(timezone.utc).year-6,-1):
        try:
            columns=["CODMUNRES","CONSPRENAT","PESO","IDADEMAE","APGAR5","IDANOMAL"]
            df=frame(pysus.ftp.sinasc(state=uf,year=y,group="DN",columns=columns,as_dataframe=True,show_progress=False))
            if df is None or df.empty:continue
            key=codes(df[col(df,["CODMUNRES","MUN_RES"])]); totals=key[key.str.len()==6].value_counts()
            if len(totals):return ({str(k):int(v) for k,v in totals.items()},str(y),ratios(df,["CODMUNRES","MUN_RES"],definitions))
        except Exception:continue
    values,period=annual(pysus.ftp.sinasc,uf,"DN",["CODMUNRES","MUN_RES"])
    return values,period,{}

def annual_sim(uf):
    def cause_rule(s):
        cause=s.astype(str).str.upper().str.replace(r"[^A-Z0-9]","",regex=True)
        return (cause.str.len()>=3,cause.str.match(r"^R(?:0[0-9]|[1-8][0-9]|9[0-9])"))
    definitions=[("causas_mal_definidas",["CAUSABAS","CAUSABAS_O"],cause_rule)]
    for y in range(datetime.now(timezone.utc).year-1,datetime.now(timezone.utc).year-6,-1):
        try:
            columns=["CODMUNRES","CAUSABAS"]
            df=frame(pysus.ftp.sim(state=uf,year=y,group="DO",columns=columns,as_dataframe=True,show_progress=False))
            if df is None or df.empty:continue
            key=codes(df[col(df,["CODMUNRES","MUN_RES"])]); totals=key[key.str.len()==6].value_counts()
            if len(totals):return ({str(k):int(v) for k,v in totals.items()},str(y),ratios(df,["CODMUNRES","MUN_RES"],definitions))
        except Exception:continue
    values,period=annual(pysus.ftp.sim,uf,"DO",["CODMUNRES","MUN_RES"])
    return values,period,{}

def collect_indicator(name, uf):
    tasks={
      "cnes":lambda:(*monthly(pysus.ftp.cnes,uf,"ST",["CODUFMUN","CO_MUNICIP"]),{}),
      "internacoes":lambda:(*monthly(pysus.ftp.sih,uf,"RD",["MUNIC_RES","MUNIC_MOV"]),{}),
      "mortalidade":lambda:annual_sim(uf),
      "nascimentos":lambda:annual_sinasc(uf),
      "ambulatorial":lambda:(*monthly(pysus.ftp.sia,uf,"PA",["PA_UFMUN","UFMUN"],"PA_QTDAPR"),{}),
    }
    return tasks[name]()

def collect_worker(name, uf, output):
    values, competence, expanded=collect_indicator(name,uf)
    Path(output).write_text(json.dumps({"values":values,"competence":competence,"expanded":expanded},separators=(",",":")),encoding="utf-8")
    del values
    gc.collect()

def main():
    p=argparse.ArgumentParser();p.add_argument("--state",required=True);uf=p.parse_args().state.upper()
    # Cada base roda em um processo isolado. Ao terminar, toda a memoria usada
    # pelo parquet e pelo DataFrame e devolvida antes da proxima base. Isso e
    # especialmente importante para o SIA de Sao Paulo.
    partial=Path("generated")/"partials";partial.mkdir(parents=True,exist_ok=True)
    results={}; context=mp.get_context("spawn")
    for name in ("cnes","internacoes","mortalidade","nascimentos","ambulatorial"):
        target=partial/f"{uf}-{name}.json"
        process=context.Process(target=collect_worker,args=(name,uf,str(target)))
        process.start();process.join()
        if process.exitcode or not target.exists():
            results[name]=({},None,{})
        else:
            item=json.loads(target.read_text(encoding="utf-8"))
            results[name]=(item["values"],item["competence"],item.get("expanded",{}))
        target.unlink(missing_ok=True)
    cnes,cnes_p,_=results["cnes"];sih,sih_p,_=results["internacoes"]
    sim,sim_p,sim_x=results["mortalidade"];nasc,nasc_p,nasc_x=results["nascimentos"]
    sia,sia_p,_=results["ambulatorial"]
    all_codes=set(cnes)|set(sih)|set(sim)|set(nasc)|set(sia)
    def expanded_for(code):
        result={}
        for collection in (sim_x,nasc_x):
            for name,values in collection.items():
                if code in values:result[name]=values[code]
        return result
    municipios={code:{"cnes":cnes.get(code),"internacoes":sih.get(code),"mortalidade":sim.get(code),
      "nascimentos":nasc.get(code),"ambulatorial":sia.get(code),"ampliados":expanded_for(code)} for code in sorted(all_codes)}
    data={"uf":uf,"atualizado_em":datetime.now(timezone.utc).isoformat(timespec="seconds"),
      "competencias":{"cnes":cnes_p,"internacoes":sih_p,"mortalidade":sim_p,"nascimentos":nasc_p,"ambulatorial":sia_p},
      "municipios":municipios}
    previous=Path("data")/"estados"/f"{uf}.json"
    if previous.exists():
        try:
            old=json.loads(previous.read_text(encoding="utf-8"))
            data["anterior"]={"competencias":old.get("competencias",{}),"municipios":old.get("municipios",{})}
        except (OSError,json.JSONDecodeError):
            pass
    out=Path("generated")/f"{uf}.json";out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(data,ensure_ascii=False,separators=(",",":")),encoding="utf-8")
if __name__=="__main__":main()
