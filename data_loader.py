import os
import glob
import re
import pandas as pd
from datetime import datetime, date

BASE_PATH = r"F:\Dados\CSCM\Indicadores\Caracterização do Stock"
STOCK_FOLDER = os.path.join(BASE_PATH, "Histórico Stock")
CARTEIRA_FOLDER = os.path.join(BASE_PATH, "Histórico Carteira")
QUARENTENA_FILE = os.path.join(STOCK_FOLDER, "Lotes Quarentena.xlsx")


def find_col(df, *keywords):
    for col in df.columns:
        col_upper = col.upper()
        if all(k.upper() in col_upper for k in keywords):
            return col
    return None


def _week_to_date(week, year):
    try:
        return date.fromisocalendar(int(year), int(week), 1)
    except Exception:
        return None


def _parse_stock_filename(path):
    m = re.search(r"W(\d+)_(\d{4})\.xlsx", os.path.basename(path), re.IGNORECASE)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None, None


def _parse_carteira_filename(path):
    m = re.search(r"_(\d{8})_(\d{2})H(\d{2})", os.path.basename(path))
    if m:
        try:
            return datetime.strptime(f"{m.group(1)}{m.group(2)}{m.group(3)}", "%Y%m%d%H%M")
        except ValueError:
            pass
    return None


def _get_all_stock_files():
    files = [
        f for f in glob.glob(os.path.join(STOCK_FOLDER, "W*.xlsx"))
        if not any(x in f for x in ["Quarentena", "Lotes"])
    ]
    result = []
    for f in files:
        week, year = _parse_stock_filename(f)
        if week and year:
            result.append((f, week, year, _week_to_date(week, year)))
    return sorted(result, key=lambda x: (x[3] or date.min))


def _get_all_carteira_files():
    files = glob.glob(os.path.join(CARTEIRA_FOLDER, "S*_Carteira Encomendas_*.xlsx"))
    result = []
    for f in files:
        dt = _parse_carteira_filename(f)
        if dt:
            result.append((f, dt))
    return sorted(result, key=lambda x: x[1])


def load_all_data(progress_callback=None):
    result = {
        "stock_latest_df": None,
        "stock_file": "N/A",
        "carteira_file": "N/A",
        "quarentena_df": None,
        "metrics": {},
        "context": "",
        "errors": [],
        "periodos_disponiveis": []
    }

    stock_files = _get_all_stock_files()
    carteira_files = _get_all_carteira_files()
    total_files = len(stock_files) + len(carteira_files)

    if not stock_files:
        result["errors"].append("Nenhum ficheiro de stock encontrado em Histórico Stock")
    if not carteira_files:
        result["errors"].append("Nenhum ficheiro de carteira encontrado em Histórico Carteira")

    # ── Carregar TODO o histórico de stock ────────────────────────
    stock_snapshots = []  # lista de (label, date, df)

    for i, (path, week, year, dt) in enumerate(stock_files):
        if progress_callback:
            progress_callback(i / max(total_files, 1), f"A ler stock {os.path.basename(path)}...")
        try:
            df = pd.read_excel(path)
            label = f"W{week:02d}_{year}"
            stock_snapshots.append((label, dt, df))
        except Exception as e:
            result["errors"].append(f"Erro ao ler {os.path.basename(path)}: {e}")

    # ── Carregar TODO o histórico de carteira ─────────────────────
    carteira_snapshots = []

    for i, (path, dt) in enumerate(carteira_files):
        if progress_callback:
            idx = len(stock_files) + i
            progress_callback(idx / max(total_files, 1), f"A ler carteira {os.path.basename(path)}...")
        try:
            df = pd.read_excel(path)
            carteira_snapshots.append((dt, df))
        except Exception as e:
            result["errors"].append(f"Erro ao ler {os.path.basename(path)}: {e}")

    # ── Quarentena ────────────────────────────────────────────────
    if os.path.exists(QUARENTENA_FILE):
        try:
            result["quarentena_df"] = pd.read_excel(QUARENTENA_FILE)
        except Exception as e:
            result["errors"].append(f"Erro ao ler quarentena: {e}")

    # ── Ficheiro mais recente (detalhe completo) ──────────────────
    if stock_snapshots:
        label_latest, dt_latest, df_latest = stock_snapshots[-1]
        result["stock_latest_df"] = df_latest
        result["stock_file"] = f"{label_latest} ({dt_latest})"

    carteira_latest_df = None
    if carteira_snapshots:
        dt_cart, carteira_latest_df = carteira_snapshots[-1]
        result["carteira_file"] = os.path.basename(carteira_files[-1][0])

    # ── Métricas da última extracção ─────────────────────────────
    result["metrics"] = _compute_metrics(
        result["stock_latest_df"], carteira_latest_df, result["quarentena_df"]
    )

    # ── Contexto completo para o agente ──────────────────────────
    result["context"] = _build_context(
        stock_snapshots, carteira_snapshots, result["quarentena_df"],
        result["metrics"], result["stock_file"], result["carteira_file"]
    )

    # Períodos disponíveis (para mostrar na UI)
    result["periodos_disponiveis"] = [
        f"{label} ({dt})" for label, dt, _ in stock_snapshots
    ]

    return result


def _compute_metrics(df_stock, df_carteira, df_quarentena):
    m = {}
    if df_stock is not None:
        total_col = find_col(df_stock, "TOTAL", "TON")
        disp_col = find_col(df_stock, "DISP", "TON")
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
        peso_col = find_col(df_quarentena, "PESO") or find_col(df_quarentena, "TON")
        if peso_col:
            m["quarentena_ton"] = df_quarentena[peso_col].sum()

    if "bloqueado_ton" in m and "alocado_carteira_ton" in m:
        m["gap_ton"] = m["bloqueado_ton"] - m["alocado_carteira_ton"]

    return m


def _build_stock_history_summary(stock_snapshots):
    """Resumo temporal: uma linha por snapshot com totais."""
    rows = []
    for label, dt, df in stock_snapshots:
        total_col = find_col(df, "TOTAL", "TON")
        disp_col = find_col(df, "DISP", "TON")
        row = {"Periodo": label, "Data": str(dt)}
        row["Total_ton"] = round(df[total_col].sum(), 2) if total_col else None
        row["Disponivel_ton"] = round(df[disp_col].sum(), 2) if disp_col else None
        if row["Total_ton"] and row["Disponivel_ton"]:
            row["Bloqueado_ton"] = round(row["Total_ton"] - row["Disponivel_ton"], 2)
        rows.append(row)
    return pd.DataFrame(rows)


def _build_carteira_history_summary(carteira_snapshots):
    """Resumo temporal da carteira: alocado por data."""
    rows = []
    for dt, df in carteira_snapshots:
        peso_col = find_col(df, "PESO") or find_col(df, "TON")
        alocado = round(df[peso_col].sum(), 2) if peso_col else None
        rows.append({"Data": str(dt.date()), "Alocado_Carteira_ton": alocado})
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

    labels = [
        ("total_ton", "Stock Total"),
        ("disponivel_ton", "Disponível"),
        ("bloqueado_ton", "Bloqueado ERP"),
        ("alocado_carteira_ton", "Alocado Carteira"),
        ("gap_ton", "Gap STK vs Carteira"),
        ("quarentena_ton", "Quarentena"),
    ]
    for key, label in labels:
        if key in metrics:
            lines.append(f"- {label}: {metrics[key]:,.2f} ton")

    # Série histórica do stock
    if stock_snapshots:
        hist = _build_stock_history_summary(stock_snapshots)
        lines.append("\n## SÉRIE HISTÓRICA DO STOCK (todos os snapshots)")
        lines.append(hist.to_csv(index=False))

    # Série histórica da carteira
    if carteira_snapshots:
        cart_hist = _build_carteira_history_summary(carteira_snapshots)
        lines.append("\n## SÉRIE HISTÓRICA DA CARTEIRA DE ENCOMENDAS")
        lines.append(cart_hist.to_csv(index=False))

    # Detalhe completo do snapshot mais recente
    if stock_snapshots:
        _, _, df_latest = stock_snapshots[-1]
        artigo_col = find_col(df_latest, "ARTIGO")
        total_col = find_col(df_latest, "TOTAL", "TON")
        disp_col = find_col(df_latest, "DISP", "TON")

        if artigo_col and total_col:
            agg = {total_col: "sum"}
            if disp_col:
                agg[disp_col] = "sum"
            grouped = df_latest.groupby(artigo_col).agg(agg).reset_index()
            grouped.columns = (
                ["ARTIGO", "TOTAL_TON"] + (["DISP_TON"] if disp_col else [])
            )
            grouped = grouped.sort_values("TOTAL_TON", ascending=False)
            lines.append("\n## STOCK ACTUAL POR ARTIGO (último snapshot, ordenado por total)")
            lines.append(grouped.to_csv(index=False))
        else:
            lines.append(f"\n## COLUNAS DO FICHEIRO STOCK: {list(df_latest.columns)}")

    # Quarentena
    if df_quarentena is not None and len(df_quarentena) > 0:
        lines.append("\n## LOTES EM QUARENTENA (actual)")
        lines.append(df_quarentena.to_csv(index=False))

    return "\n".join(lines)
