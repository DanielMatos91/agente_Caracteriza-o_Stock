import io
import pandas as pd
import requests
import streamlit as st
from datetime import datetime, date

ONEDRIVE_URL = (
    "https://cabeltept-my.sharepoint.com/:x:/g/personal/daniel_matos_cabelte_pt"
    "/IQBtRls7_93QQIbemvifSHHSAYrsoiYpX1-V29WVApXe5CY?e=Y83Wqv&download=1"
)


def find_col(df, *keywords):
    for col in df.columns:
        col_upper = col.upper()
        if all(k.upper() in col_upper for k in keywords):
            return col
    return None


@st.cache_data(ttl=3600)
def _download_raw() -> bytes:
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
        result["errors"].append(f"Erro ao descarregar ficheiro OneDrive: {e}")
        return result

    if progress_callback:
        progress_callback(0.3, "A ler sheets do Excel...")

    try:
        sheets = pd.read_excel(io.BytesIO(raw), sheet_name=None)
    except Exception as e:
        result["errors"].append(f"Erro ao ler o ficheiro Excel: {e}")
        return result

    df_stock_all    = sheets.get("Stock")
    df_carteira_all = sheets.get("Carteira")
    df_quarentena   = sheets.get("Quarentena")

    if df_stock_all is None:
        result["errors"].append("Sheet 'Stock' não encontrada no ficheiro.")
    if df_carteira_all is None:
        result["errors"].append("Sheet 'Carteira' não encontrada no ficheiro.")
    if df_quarentena is None:
        result["errors"].append("Sheet 'Quarentena' não encontrada no ficheiro.")
    else:
        result["quarentena_df"] = df_quarentena

    if progress_callback:
        progress_callback(0.5, "A processar histórico de stock...")

    # ── Snapshots de stock (agrupados por DATA EXTRAÇÃO) ──────────────
    stock_snapshots = []
    if df_stock_all is not None:
        date_col = find_col(df_stock_all, "DATA", "EXTRA") or find_col(df_stock_all, "DATA")
        if date_col:
            df_stock_all[date_col] = pd.to_datetime(df_stock_all[date_col], errors="coerce")
            for dt, grp in df_stock_all.groupby(date_col, sort=True):
                try:
                    iso = dt.isocalendar()
                    label = f"W{iso.week:02d}_{iso.year}"
                except Exception:
                    label = str(dt.date())
                stock_snapshots.append((label, dt.date(), grp.reset_index(drop=T
        else:
            stock_snapshots.append(("Actual", date.today(), df_stock_all))

    if progress_callback:
        progress_callback(0.7, "A processar histórico de carteira...")

    # ── Snapshots de carteira (agrupados por DATA EXTRAÇÃO) ───────────
    carteira_snapshots = []
    if df_carteira_all is not None:
        date_col = find_col(df_carteira_all, "DATA", "EXTRA") or find_col(df_car
        if date_col:
            df_carteira_all[date_col] = pd.to_datetime(df_carteira_all[date_col]
            for dt, grp in df_carteira_all.groupby(date_col, sort=True):
                carteira_snapshots.append((dt, grp.reset_index(drop=True)))
        else:
            carteira_snapshots.append((datetime.now(), df_carteira_all))

    # ── Snapshot mais recente ─────────────────────────────────────────
    if stock_snapshots:
        label_l, dt_l, df_l = stock_snapshots[-1]
        result["stock_latest_df"] = df_l
        result["stock_file"] = f"{label_l} ({dt_l})"

    carteira_latest_df = None
    if carteira_snapshots:
        dt_c, carteira_latest_df = carteira_snapshots[-1]
        result["carteira_file"] = str(dt_c.date() if hasattr(dt_c, "date") else dt_c)

    result["stock_snapshots"]    = stock_snapshots
    result["carteira_snapshots"] = carteira_snapshots

    if progress_callback:
        progress_callback(0.9, "A calcular métricas...")

    result["metrics"] = _compute_metrics(
        result["stock_latest_df"], carteira_latest_df, result["quarentena_df"]
    )
    result["context"] = _build_context(
        stock_snapshots, carteira_snapshots, result["quarentena_df"],
        result["metrics"], result["stock_file"], result["carteira_file"]
    )
    result["periodos_disponiveis"] = [
        f"{label} ({dt})" for label, dt, _ in stock_snapshots
    ]

    if progress_callback:
        progress_callback(1.0, "Concluído.")

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
        peso_col = find_col(df_carteira, "PESO") or find_col(df_carteira, "TON")
        if peso_col:
            m["alocado_carteira_ton"] = df_carteira[peso_col].sum()

    if df_quarentena is not None:
        peso_col = find_col(df_quarentena, "PESO") or find_col(df_quarentena, "T
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
        row["Total_ton"]     = round(df[total_col].sum(), 2) if total_col else N
        row["Disponivel_ton"] = round(df[disp_col].sum(), 2) if disp_col else None
        if row["Total_ton"] and row["Disponivel_ton"]:
            row["Bloqueado_ton"] = round(row["Total_ton"] - row["Disponivel_ton"], 2)
        rows.append(row)
    return pd.DataFrame(rows)


def _build_carteira_history_summary(carteira_snapshots):
    rows = []
    for dt, df in carteira_snapshots:
        peso_col = find_col(df, "PESO") or find_col(df, "TON")
        alocado  = round(df[peso_col].sum(), 2) if peso_col else None
        rows.append({"Data": str(dt.date() if hasattr(dt, "date") else dt), "Alocado_Carteira_ton": alocado})
    return pd.DataFrame(rows)


def _build_context(stock_snapshots, carteira_snapshots, df_quarentena, metrics, stock_file, carteira_file):
    lines = [
        "=== DADOS HISTÓRICOS DO STOCK CABELTE ===",
        f"Extracção mais recente stock: {stock_file}",
        f"Extracção mais recente carteira: {carteira_file}",
        f"Total de snapshots de stock disponíveis: {len(stock_snapshots)}",
        f"Total de snapshots de carteira disponíveis: {len(carteira_snapshots)}",
        "",
        "## MÉTRICAS DA ÚLTIMA EXTRACÇÃO",
    ]

    for key, label in [
        ("total_ton",           "Stock Total"),
        ("disponivel_ton",      "Disponível"),
        ("bloqueado_ton",       "Bloqueado ERP"),
        ("alocado_carteira_ton","Alocado Carteira"),
        ("gap_ton",             "Gap STK vs Carteira"),
        ("quarentena_ton",      "Quarentena"),
    ]:
        if key in metrics:
            lines.append(f"- {label}: {metrics[key]:,.2f} ton")

    if stock_snapshots:
        hist = _build_stock_history_summary(stock_snapshots)
        lines.append("\n## SÉRIE HISTÓRICA DO STOCK (todos os snapshots)")
        lines.append(hist.to_csv(index=False))

    if carteira_snapshots:
        cart_hist = _build_carteira_history_summary(carteira_snapshots)
        lines.append("\n## SÉRIE HISTÓRICA DA CARTEIRA DE ENCOMENDAS")
        lines.append(cart_hist.to_csv(index=False))

    if stock_snapshots:
        _, _, df_latest = stock_snapshots[-1]
        artigo_col = find_col(df_latest, "ARTIGO")
        total_col  = find_col(df_latest, "TOTAL", "TON")
        disp_col   = find_col(df_latest, "DISP", "TON")

        if artigo_col and total_col:
            agg = {total_col: "sum"}
            if disp_col:
                agg[disp_col] = "sum"
            grouped = df_latest.groupby(artigo_col).agg(agg).reset_index()
            grouped.columns = ["ARTIGO", "TOTAL_TON"] + (["DISP_TON"] if disp_co
            grouped = grouped.sort_values("TOTAL_TON", ascending=False)
            lines.append("\n## STOCK ACTUAL POR ARTIGO (último snapshot, ordenad
            lines.append(grouped.to_csv(index=False))
        else:
            lines.append(f"\n## COLUNAS DO FICHEIRO STOCK: {list(df_latest.columns)}")

    if df_quarentena is not None and len(df_quarentena) > 0:
        lines.append("\n## LOTES EM QUARENTENA (actual)")
        lines.append(df_quarentena.to_csv(index=False))

    return "\n".join(lines)
