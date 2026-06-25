import io
import pandas as pd
import requests
import streamlit as st
from datetime import datetime, date

ONEDRIVE_URL = (
    "https://cabeltept-my.sharepoint.com/:x:/g/personal"
    "/daniel_matos_cabelte_pt"
    "/IQBtRls7_93QQIbemvifSHHSAYrsoiYpX1-V29WVApXe5CY"
    "?e=Y83Wqv&download=1"
)


def find_col(df, *keywords):
    for col in df.columns:
        col_upper = col.upper()
        if all(k.upper() in col_upper for k in keywords):
            return col
    return None


@st.cache_data(ttl=3600)
def _download_raw():
    r = requests.get(ONEDRIVE_URL, allow_redirects=True, timeout=60)
    r.raise_for_status()
    return r.content


def load_all_data(progress_callback=None):
    result = {
        "stock_latest_df": None,
        "stock_file": "N/A",
        "carteira_file": "N/A",
        "quarentena_df": None,
        "metrics": {},
        "context": "",
        "errors": [],
        "periodos_disponiveis": [],
        "stock_snapshots": [],
        "carteira_snapshots": [],
    }

    if progress_callback:
        progress_callback(0.1, "A descarregar ficheiro do OneDrive...")

    try:
        raw = _download_raw()
    except Exception as e:
        result["errors"].append(f"Erro ao descarregar: {e}")
        return result

    if progress_callback:
        progress_callback(0.3, "A ler sheets do Excel...")

    try:
        sheets = pd.read_excel(io.BytesIO(raw), sheet_name=None)
    except Exception as e:
        result["errors"].append(f"Erro ao ler Excel: {e}")
        return result

    df_stock_all    = sheets.get("Stock")
    df_carteira_all = sheets.get("Carteira")
    df_quarentena   = sheets.get("Quarentena")

    if df_stock_all is None:
        result["errors"].append("Sheet 'Stock' nao encontrada.")
    if df_carteira_all is None:
        result["errors"].append("Sheet 'Carteira' nao encontrada.")
    if df_quarentena is None:
        result["errors"].append("Sheet 'Quarentena' nao encontrada.")
    else:
        result["quarentena_df"] = df_quarentena

    if progress_callback:
        progress_callback(0.5, "A processar stock...")

    stock_snapshots = []
    if df_stock_all is not None:
        dcol = (
            find_col(df_stock_all, "DATA", "EXTRA")
            or find_col(df_stock_all, "DATA")
        )
        if dcol:
            df_stock_all[dcol] = pd.to_datetime(
                df_stock_all[dcol], errors="coerce"
            )
            for dt, grp in df_stock_all.groupby(dcol, sort=True):
                try:
                    iso = dt.isocalendar()
                    label = f"W{iso.week:02d}_{iso.year}"
                except Exception:
                    label = str(dt.date())
                stock_snapshots.append(
                    (label, dt.date(), grp.reset_index(drop=True))
                )
        else:
            stock_snapshots.append(
                ("Actual", date.today(), df_stock_all)
            )

    if progress_callback:
        progress_callback(0.7, "A processar carteira...")

    carteira_snapshots = []
    if df_carteira_all is not None:
        dcol = (
            find_col(df_carteira_all, "DATA", "EXTRA")
            or find_col(df_carteira_all, "DATA")
        )
        if dcol:
            df_carteira_all[dcol] = pd.to_datetime(
                df_carteira_all[dcol], errors="coerce"
            )
            for dt, grp in df_carteira_all.groupby(dcol, sort=True):
                carteira_snapshots.append(
                    (dt, grp.reset_index(drop=True))
                )
        else:
            carteira_snapshots.append((datetime.now(), df_carteira_all))

    if stock_snapshots:
        label_l, dt_l, df_l = stock_snapshots[-1]
        result["stock_latest_df"] = df_l
        result["stock_file"] = f"{label_l} ({dt_l})"

    carteira_latest_df = None
    if carteira_snapshots:
        dt_c, carteira_latest_df = carteira_snapshots[-1]
        result["carteira_file"] = str(
            dt_c.date() if hasattr(dt_c, "date") else dt_c
        )

    result["stock_snapshots"]    = stock_snapshots
    result["carteira_snapshots"] = carteira_snapshots

    if progress_callback:
        progress_callback(0.9, "A calcular metricas...")

    result["metrics"] = _compute_metrics(
        result["stock_latest_df"],
        carteira_latest_df,
        result["quarentena_df"],
    )
    result["context"] = _build_context(
        stock_snapshots,
        carteira_snapshots,
        result["quarentena_df"],
        result["metrics"],
        result["stock_file"],
        result["carteira_file"],
    )
    result["periodos_disponiveis"] = [
        f"{label} ({dt})" for label, dt, _ in stock_snapshots
    ]

    if progress_callback:
        progress_callback(1.0, "Concluido.")

    return result


def _compute_metrics(df_stock, df_carteira, df_quarentena):
    m = {}
    if df_stock is not None:
        total_col = find_col(df_stock, "TOTAL", "TON")
        disp_col  = find_col(df_stock, "DISP", "TON")
        if total_col:
            m["total_ton"] = df_stock[total_col].sum()
        if disp_col:
            m["disponivel_ton"] = df_stock[disp_col].sum()
        if "total_ton" in m and "disponivel_ton" in m:
            m["bloqueado_ton"] = m["total_ton"] - m["disponivel_ton"]

    if df_carteira is not None:
        peso_col = (
            find_col(df_carteira, "PESO")
            or find_col(df_carteira, "TON")
        )
        if peso_col:
            m["alocado_carteira_ton"] = df_carteira[peso_col].sum()

    if df_quarentena is not None:
        peso_col = (
            find_col(df_quarentena, "PESO")
            or find_col(df_quarentena, "TON")
        )
        if peso_col:
            m["quarentena_ton"] = df_quarentena[peso_col].sum()

    if "bloqueado_ton" in m and "alocado_carteira_ton" in m:
        m["gap_ton"] = m["bloqueado_ton"] - m["alocado_carteira_ton"]

    return m


def _build_stock_history_summary(stock_snapshots):
    rows = []
    for label, dt, df in stock_snapshots:
        total_col = find_col(df, "TOTAL", "TON")
        disp_col  = find_col(df, "DISP", "TON")
        row = {"Periodo": label, "Data": str(dt)}
        row["Total_ton"] = (
            round(df[total_col].sum(), 2) if total_col else None
        )
        row["Disponivel_ton"] = (
            round(df[disp_col].sum(), 2) if disp_col else None
        )
        if row["Total_ton"] and row["Disponivel_ton"]:
            row["Bloqueado_ton"] = round(
                row["Total_ton"] - row["Disponivel_ton"], 2
            )
        rows.append(row)
    return pd.DataFrame(rows)


def _build_carteira_history_summary(carteira_snapshots):
    rows = []
    for dt, df in carteira_snapshots:
        peso_col = (
            find_col(df, "PESO") or find_col(df, "TON")
        )
        alocado = round(df[peso_col].sum(), 2) if peso_col else None
        data_str = str(dt.date() if hasattr(dt, "date") else dt)
        rows.append({
            "Data": data_str,
            "Alocado_Carteira_ton": alocado,
        })
    return pd.DataFrame(rows)


def _build_context(
    stock_snapshots, carteira_snapshots,
    df_quarentena, metrics, stock_file, carteira_file
):
    lines = [
        "=== DADOS HISTORICOS DO STOCK CABELTE ===",
        f"Extracao mais recente stock: {stock_file}",
        f"Extracao mais recente carteira: {carteira_file}",
        f"Snapshots stock: {len(stock_snapshots)}",
        f"Snapshots carteira: {len(carteira_snapshots)}",
        "",
        "## METRICAS DA ULTIMA EXTRACAO",
    ]

    for key, label in [
        ("total_ton",            "Stock Total"),
        ("disponivel_ton",       "Disponivel"),
        ("bloqueado_ton",        "Bloqueado ERP"),
        ("alocado_carteira_ton", "Alocado Carteira"),
        ("gap_ton",              "Gap STK vs Carteira"),
        ("quarentena_ton",       "Quarentena"),
    ]:
        if key in metrics:
            lines.append(f"- {label}: {metrics[key]:,.2f} ton")

    if stock_snapshots:
        hist = _build_stock_history_summary(stock_snapshots)
        lines.append("\n## SERIE HISTORICA DO STOCK")
        lines.append(hist.to_csv(index=False))

    if carteira_snapshots:
        ch = _build_carteira_history_summary(carteira_snapshots)
        lines.append("\n## SERIE HISTORICA DA CARTEIRA")
        lines.append(ch.to_csv(index=False))

    if stock_snapshots:
        _, _, df_latest = stock_snapshots[-1]
        artigo_col = find_col(df_latest, "ARTIGO")
        total_col  = find_col(df_latest, "TOTAL", "TON")
        disp_col   = find_col(df_latest, "DISP", "TON")

        if artigo_col and total_col:
            agg = {total_col: "sum"}
            if disp_col:
                agg[disp_col] = "sum"
            grouped = (
                df_latest.groupby(artigo_col)
                .agg(agg)
                .reset_index()
            )
            cols = ["ARTIGO", "TOTAL_TON"]
            if disp_col:
                cols.append("DISP_TON")
            grouped.columns = cols
            grouped = grouped.sort_values(
                "TOTAL_TON", ascending=False
            )
            lines.append("\n## STOCK POR ARTIGO (ultimo snapshot)")
            lines.append(grouped.to_csv(index=False))
        else:
            lines.append(
                f"\n## COLUNAS STOCK: {list(df_latest.columns)}"
            )

    if df_quarentena is not None and len(df_quarentena) > 0:
        lines.append("\n## LOTES EM QUARENTENA")
        lines.append(df_quarentena.to_csv(index=False))

    return "\n".join(lines)
