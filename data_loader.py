  import os
  import glob
  import re
  import pandas as pd
  import requests
  import io
  import streamlit as st
  from datetime import datetime, date

  ONEDRIVE_URL = "https://cabeltept-my.sharepoint.com/:x:/g/personal/daniel_matos_cabelte_pt/IQBtRls7_93QQIbemvifSHHSAYrsoiYpX1-V29WVApXe5CY?e=Y83Wqv"

  @st.cache_data(ttl=3600)  # cache 1h — não descarrega a cada mensagem do chat
  def load_all_data():
      r = requests.get(ONEDRIVE_URL, allow_redirects=True)
      r.raise_for_status()
      buf = io.BytesIO(r.content)

      return {
          "stock":      pd.read_excel(buf, sheet_name="Stock"),
          "carteira":   pd.read_excel(buf, sheet_name="Carteira"),
          "quarentena": pd.read_excel(buf, sheet_name="Quarentena"),
      }

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
          "per
  ──── (128 lines hidden) ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
  etrics, stock_file, carteira_file):
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
