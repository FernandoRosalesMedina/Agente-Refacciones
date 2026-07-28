#!/usr/bin/env python3
"""
Cruza la matriz de criticidad (602 refacciones, cambia poco) contra el
export diario de SAP ZMADE, y genera:
  - data/maestro.json      (usado por index.html)
  - data/historial_kpis.json (snapshot de indicadores, para tendencia)

Match: Codigo Comun (GM) [matriz] == Material [ZMADE]. Es el mismo criterio
que ya usabas manualmente (reproduce el 79% de match conocido).

Acepta ZMADE en .csv o .xlsx (detecta automáticamente la fila de encabezados).

Uso diario (lo único que cambia es el ZMADE):
    python scripts/generar_datos.py data/matriz_criticidad.xlsx data/ZMADE.csv
"""

import sys
import json
from pathlib import Path
from datetime import datetime, timezone

import pandas as pd

COLS_CRITICIDAD = [
    "Taller", "Codigo Comun (GM)", "Numero de Parte Fabricante", "Descripcion",
    "Fabricante (Matriz)", "Partes por Maquina", "Costo Unitario MXN",
    "Lead Time (dias)", "Stock (Matriz Criticidad)", "Min", "Max",
]

def cargar_matriz(ruta_matriz: str) -> pd.DataFrame:
    df = pd.read_excel(ruta_matriz)
    faltantes = [c for c in COLS_CRITICIDAD if c not in df.columns]
    if faltantes:
        print(f"Aviso: faltan columnas en la matriz de criticidad: {faltantes}")
    return df[[c for c in COLS_CRITICIDAD if c in df.columns]].copy()


def _detectar_fila_encabezado(lineas_o_filas, columna_ancla="Material") -> int:
    """Busca la fila que contiene la columna ancla (ej. 'Material') entre las
    primeras filas del archivo. Sirve tanto si el archivo trae filas de título
    arriba (como el .xlsx crudo de SAP) como si el CSV ya viene limpio y el
    encabezado está en la fila 0."""
    for i, fila in enumerate(lineas_o_filas[:20]):
        if columna_ancla in [str(c).strip() for c in fila]:
            return i
    return 0  # si no encuentra el ancla, asume que el encabezado ya es la fila 0


def cargar_zmade(ruta_zmade: str) -> pd.DataFrame:
    ruta = Path(ruta_zmade)
    es_csv = ruta.suffix.lower() == ".csv"

    if es_csv:
        # Detecta separador (coma o punto y coma, común en exports regionales)
        muestra_bruta = pd.read_csv(ruta, header=None, sep=None, engine="python", nrows=20, dtype=str)
        fila_header = _detectar_fila_encabezado(muestra_bruta.values.tolist())
        df = pd.read_csv(ruta, header=fila_header, sep=None, engine="python")
    else:
        muestra_bruta = pd.read_excel(ruta, sheet_name=0, header=None, nrows=20)
        fila_header = _detectar_fila_encabezado(muestra_bruta.values.tolist())
        df = pd.read_excel(ruta, sheet_name=0, header=fila_header)

    df.columns = [str(c).strip() for c in df.columns]
    if "Material" not in df.columns:
        raise ValueError(
            f"No se encontró la columna 'Material' en {ruta_zmade}. "
            f"Columnas detectadas: {list(df.columns)}"
        )

    df = df.dropna(subset=["Material"])
    cols = ["Material", "Texto breve de material", "LibrUtiliz", "Pto.pedido",
            "StockMáx", "Alm.", "Nombre Fabricante"]
    df = df[[c for c in cols if c in df.columns]].copy()
    # Si un material aparece en varios almacenes, se suma el stock y se listan los almacenes
    agregaciones = {c: "first" for c in df.columns if c not in ("Material", "LibrUtiliz", "Pto.pedido", "StockMáx", "Alm.")}
    if "LibrUtiliz" in df.columns: agregaciones["LibrUtiliz"] = "sum"
    if "Pto.pedido" in df.columns: agregaciones["Pto.pedido"] = "sum"
    if "StockMáx" in df.columns: agregaciones["StockMáx"] = "sum"
    if "Alm." in df.columns: agregaciones["Alm."] = lambda x: ",".join(sorted({_fmt_almacen(v) for v in x if pd.notna(v)}))
    agg = df.groupby("Material").agg(agregaciones).reset_index()
    return agg


def _fmt_almacen(v) -> str:
    try:
        return str(int(float(v)))
    except (ValueError, TypeError):
        return str(v)


def cruzar(matriz: pd.DataFrame, zmade: pd.DataFrame) -> pd.DataFrame:
    cruce = matriz.merge(
        zmade, left_on="Codigo Comun (GM)", right_on="Material",
        how="left", indicator=True,
    )
    cruce["fuente_stock_sap"] = cruce["_merge"].map({
        "both": "OK - cruzado con ZMADE",
        "left_only": "SIN CRUCE - revisar codigo",
    })
    # "Material" y "Texto breve de material" son redundantes con
    # "Codigo Comun (GM)" y "Descripcion" de la matriz de criticidad.
    cruce = cruce.drop(columns=["_merge", "Material", "Texto breve de material"])

    renombres = {
        "Taller": "taller",
        "Codigo Comun (GM)": "codigo_gm",
        "Numero de Parte Fabricante": "no_parte_fabricante",
        "Descripcion": "descripcion",
        "Fabricante (Matriz)": "fabricante_matriz",
        "Partes por Maquina": "partes_por_maquina",
        "Costo Unitario MXN": "costo_unitario_mxn",
        "Lead Time (dias)": "lead_time_dias",
        "Stock (Matriz Criticidad)": "stock_matriz_criticidad",
        "Min": "min",
        "Max": "max",
        "LibrUtiliz": "stock_sap",
        "Pto.pedido": "punto_reorden_sap",
        "StockMáx": "stock_maximo_sap",
        "Alm.": "almacenes_sap",
        "Nombre Fabricante": "fabricante_sap",
    }
    cruce = cruce.rename(columns=renombres)
    return cruce


def limpiar_nan(registros: list) -> list:
    """pandas no puede guardar None en columnas float (revierte a NaN),
    así que se limpia ya convertido a lista de dicts, justo antes del JSON."""
    limpios = []
    for r in registros:
        limpios.append({
            k: (None if isinstance(v, float) and pd.isna(v) else v)
            for k, v in r.items()
        })
    return limpios


def calcular_kpis(refacciones: list) -> dict:
    total = len(refacciones)
    cruzadas = sum(1 for r in refacciones if r.get("fuente_stock_sap") == "OK - cruzado con ZMADE")
    sin_stock = sum(1 for r in refacciones if r.get("stock_sap") in (0, None, 0.0))
    bajo_minimo = sum(
        1 for r in refacciones
        if r.get("stock_sap") is not None and r.get("min") is not None
        and r["stock_sap"] < r["min"]
    )
    return {
        "total": total,
        "match_rate": round(cruzadas / total, 4) if total else None,
        "sin_cruce": total - cruzadas,
        "sin_stock": sin_stock,
        "bajo_minimo": bajo_minimo,
    }


def actualizar_historial(kpis: dict, ruta_historial: str = "data/historial_kpis.json"):
    ruta = Path(ruta_historial)
    historial = json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else []
    historial.append({"fecha": datetime.now(timezone.utc).isoformat(), **kpis})
    historial = historial[-200:]
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(historial, ensure_ascii=False, indent=2), encoding="utf-8")


def generar(ruta_matriz: str, ruta_zmade: str, ruta_salida: str = "data/maestro.json"):
    matriz = cargar_matriz(ruta_matriz)
    zmade = cargar_zmade(ruta_zmade)
    cruce = cruzar(matriz, zmade)
    refacciones = limpiar_nan(cruce.to_dict(orient="records"))
    kpis = calcular_kpis(refacciones)

    salida = {
        "generado": datetime.now(timezone.utc).isoformat(),
        "fuente": {
            "matriz_criticidad": Path(ruta_matriz).name,
            "zmade": Path(ruta_zmade).name,
            **kpis,
        },
        "refacciones": refacciones,
    }

    Path(ruta_salida).parent.mkdir(parents=True, exist_ok=True)
    Path(ruta_salida).write_text(json.dumps(salida, ensure_ascii=False, indent=2), encoding="utf-8")
    actualizar_historial(kpis)

    print(f"OK: {kpis['total']} refacciones, {kpis['sin_cruce']} sin cruce, {kpis['sin_stock']} en stock 0.")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Uso: python scripts/generar_datos.py <matriz_criticidad.xlsx> <ZMADE.csv|ZMADE.xlsx>")
        sys.exit(1)
    generar(sys.argv[1], sys.argv[2])
