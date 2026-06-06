import tkinter as tk
from tkinter import ttk, messagebox
import webbrowser
import threading
import queue
import os
import re
import pandas as pd
from datetime import datetime
import yfinance as yf

from config import APP_TITLE, COL_INFOS, CACHE_DIR
import analyzer

class ScreenerApp:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("1440x700")
        
        self.queue = queue.Queue()
        self.is_running = False
        self.stop_requested = False
        self.us_market_cap_data = analyzer.load_us_market_cap_cache()
        self.current_session_data = []
        
        self.selected_row_idx = -1
        self.row_widgets = {} 
        
        self.top_n_int = tk.IntVar(value=50)
        self.top_n_var = tk.StringVar(value="50")
        self.top_n_var.trace_add("write", self.sync_scale_from_entry)
        
        self.col_infos = COL_INFOS
        
        self.create_widgets()
        self.check_queue()

    def sync_scale_from_entry(self, *args):
        try:
            val = int(self.top_n_var.get())
            if 1 <= val <= 100:
                self.top_n_int.set(val)
        except:
            pass

    def sync_entry_from_scale(self, val):
        self.top_n_var.set(val)

    def create_widgets(self):
        frame_top = tk.Frame(self.root, padx=10, pady=10)
        frame_top.pack(fill=tk.X)
        
        tk.Label(frame_top, text="시장:").pack(side=tk.LEFT, padx=2)
        self.market_var = tk.StringVar(value="미국")
        combo_market = ttk.Combobox(frame_top, textvariable=self.market_var, values=["한국", "미국"], width=5, state="readonly")
        combo_market.pack(side=tk.LEFT, padx=2)
        
        tk.Label(frame_top, text="순위:").pack(side=tk.LEFT, padx=(10, 2))
        self.scale_rank = tk.Scale(frame_top, from_=1, to=100, orient=tk.HORIZONTAL, variable=self.top_n_int, showvalue=0, length=150, command=self.sync_entry_from_scale)
        self.scale_rank.pack(side=tk.LEFT, padx=2)
        self.ent_rank = tk.Entry(frame_top, textvariable=self.top_n_var, width=5)
        self.ent_rank.pack(side=tk.LEFT, padx=2)
        
        self.opt_fundamental = tk.BooleanVar(value=True)
        self.opt_peak = tk.BooleanVar(value=True)
        
        self.btn_run = tk.Button(frame_top, text="🔄 새로 검색", bg="#4CAF50", fg="white", font=("맑은 고딕", 9, "bold"), command=self.start_screening)
        self.btn_run.pack(side=tk.LEFT, padx=5)

        self.btn_load = tk.Button(frame_top, text="📂 불러오기", bg="#FF9800", fg="white", font=("맑은 고딕", 9, "bold"), command=self.fast_load_from_csv)
        self.btn_load.pack(side=tk.LEFT, padx=5)

        self.btn_stop = tk.Button(frame_top, text="⏹ 중지", bg="#F44336", fg="white", font=("맑은 고딕", 9, "bold"), command=self.stop_screening, state=tk.DISABLED)
        self.btn_stop.pack(side=tk.LEFT, padx=5)
        
        frame_progress = tk.Frame(self.root, padx=10, pady=5)
        frame_progress.pack(fill=tk.X)
        
        self.lbl_status = tk.Label(frame_progress, text="대기 중...", font=("맑은 고딕", 9), fg="#666666")
        self.lbl_status.pack(side=tk.LEFT, padx=5)
        
        self.progress = ttk.Progressbar(frame_progress, orient="horizontal", mode="determinate")
        self.progress.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        
        frame_table = tk.Frame(self.root, padx=10, pady=10)
        frame_table.pack(fill=tk.BOTH, expand=True)
        
        self.frame_header = tk.Frame(frame_table, height=30, bg="#E0E0E0")
        self.frame_header.pack(fill=tk.X, side=tk.TOP) 
        
        for idx, col in enumerate(self.col_infos):
            self.frame_header.grid_columnconfigure(idx, minsize=col["width"])
            btn = tk.Button(
                self.frame_header, text=col["text"], font=("맑은 고딕", 9, "bold"),
                command=lambda c=col["id"]: self.sort_by_column(c),
                relief="flat", bg="#EBEBEB", activebackground="#D6D6D6"
            )
            btn.grid(row=0, column=idx, sticky="nsew", padx=1, pady=1)
            
        self.canvas = tk.Canvas(frame_table, bd=0, highlightthickness=0, bg="white")
        self.scrollbar = ttk.Scrollbar(frame_table, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = tk.Frame(self.canvas, bg="white")
        
        for idx, col in enumerate(self.col_infos):
            self.scrollable_frame.grid_columnconfigure(idx, minsize=col["width"])
            
        self.canvas_window = self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        
        self.scrollable_frame.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        def _on_mousewheel(event):
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        self.canvas.bind_all("<MouseWheel>", _on_mousewheel)
        
        self.sort_ascending = True

    def select_row(self, row_idx):
        if self.selected_row_idx != -1 and self.selected_row_idx in self.row_widgets:
            old_bg = "#FFFFFF" if self.selected_row_idx % 2 == 0 else "#F9F9F9"
            for lbl in self.row_widgets[self.selected_row_idx]:
                lbl.config(bg=old_bg)
        
        self.selected_row_idx = row_idx
        if row_idx in self.row_widgets:
            for lbl in self.row_widgets[row_idx]:
                lbl.config(bg="#FFF9C4") 

    def get_csv_filename(self):
        today = datetime.now().strftime('%Y%m%d')
        market = "US" if self.market_var.get() == "미국" else "KR"
        return os.path.join(CACHE_DIR, f"screener_backup_{market}_{today}.csv")

    def fast_load_from_csv(self):
        if self.is_running: return
        filename = self.get_csv_filename()
        
        if not os.path.exists(filename):
            messagebox.showinfo("알림", "오늘 저장된 스크리닝 결과가 없습니다.\n[새로 검색]을 먼저 진행해 주세요.")
            return
            
        try:
            df = pd.read_csv(filename, encoding='utf-8-sig')
            records = df.to_dict('records')
            self.current_session_data = records
            self.redraw_table()
            self.lbl_status.config(text=f"✅ 저장된 결과를 1초 만에 불러왔습니다! ({len(records)} 종목)")
        except Exception as e:
            messagebox.showerror("오류", f"파일을 불러오는 중 오류가 발생했습니다:\n{e}")

    def stop_screening(self):
        if self.is_running:
            self.stop_requested = True
            self.lbl_status.config(text="사용자가 중지를 요청했습니다. 현재 종목까지만 처리하고 종료합니다...")
            self.btn_stop.config(state=tk.DISABLED)

    def check_queue(self):
        try:
            while True:
                msg = self.queue.get_nowait()
                m_type = msg.get("type")
                if m_type == "progress":
                    self.progress["value"] = msg["value"]
                    self.lbl_status.config(text=msg["text"])
                elif m_type == "data":
                    self.current_session_data.append(msg["data"])
                    self.insert_row_from_dict(msg["data"])
                elif m_type == "done" or m_type == "stopped":
                    if self.current_session_data and not self.stop_requested:
                        try:
                            df = pd.DataFrame(self.current_session_data)
                            df.to_csv(self.get_csv_filename(), index=False, encoding='utf-8-sig')
                        except: pass
                    
                    self.is_running = False
                    self.btn_run.config(state=tk.NORMAL)
                    self.btn_load.config(state=tk.NORMAL)
                    self.btn_stop.config(state=tk.DISABLED)
                    
                    today_str = datetime.now().strftime('%Y-%m-%d')
                    
                    if m_type == "stopped":
                        self.lbl_status.config(text=f"중지됨: 총 {msg['count']}개 종목까지만 분석되었습니다.")
                    else:
                        self.lbl_status.config(text=f"완료! (기준일: {today_str}) 총 {msg['count']}개 종목 분석 완료 (자동 백업됨)")
                        messagebox.showinfo("완료", msg["text"])
                        
                elif m_type == "error":
                    self.is_running = False
                    self.btn_run.config(state=tk.NORMAL)
                    self.btn_load.config(state=tk.NORMAL)
                    self.btn_stop.config(state=tk.DISABLED)
                    messagebox.showerror("오류", msg["text"])
        except queue.Empty: pass
        self.root.after(100, self.check_queue)

    def insert_row_from_dict(self, data):
        row_idx = len(self.current_session_data) - 1
        if row_idx < 0: row_idx = 0
        self.render_row(data, row_idx)

    def render_row(self, data, row_idx):
        is_us = self.market_var.get() == "미국"
        mcap_str = f"{data['market_cap']:,}억" if data.get('market_cap', 0) > 0 else "N/A"
        price_str = f"${data['price']:.2f}" if is_us else f"{int(data['price']):,}원"
        ma_str = f"${data['ma200']:.2f}" if is_us else f"{int(data['ma200']):,}원"
        
        diff_val = float(data['diff']) if not pd.isna(data['diff']) else 0.0
        if diff_val > 0:
            diff_str = f"+{diff_val:.2f}%"
            diff_color = "#D32F2F"
        elif diff_val < 0:
            diff_str = f"{diff_val:.2f}%"
            diff_color = "#1976D2"
        else:
            diff_str = "0.00%"
            diff_color = "#212121"
        
        rsi_val = float(data.get("rsi", 50.0))
        if rsi_val >= 70:
            rsi_str = f"{rsi_val:.1f} (과열)"
            rsi_color = "#D32F2F"
        elif rsi_val <= 30:
            rsi_str = f"{rsi_val:.1f} (과매도)"
            rsi_color = "#1976D2"
        elif rsi_val >= 50:
            rsi_str = f"{rsi_val:.1f} (보통)"
            rsi_color = "#E65100"
        else:
            rsi_str = f"{rsi_val:.1f} (침체)"
            rsi_color = "#555555"
            
        per_str = str(data.get("per", "비활성"))
        pbr_str = str(data.get("pbr", "비활성"))
        
        def parse_grade_color(text):
            if "적자" in text or "자본잠식" in text: return "#B71C1C"
            elif "초저평가" in text or "절대저평가" in text: return "#1976D2"
            elif "적정" in text: return "#388E3C"
            elif "초고평가" in text: return "#D32F2F"
            elif "고평가" in text: return "#F57C00"
            return "#757575"
            
        per_color = parse_grade_color(per_str)
        pbr_color = parse_grade_color(pbr_str)
        
        peak_str = str(data.get("peak", "비활성"))
        peak_diff_str = str(data.get("peak_diff", "비활성"))
        
        if "🔴" in peak_diff_str or "+" in peak_diff_str: peak_diff_color = "#D32F2F"
        elif "🔵" in peak_diff_str or "-" in peak_diff_str: peak_diff_color = "#1976D2"
        else: peak_diff_color = "#212121"
        
        row_cells = [
            (str(data.get("rank", "")), "#212121"),
            (str(data.get("symbol", "")), "#212121"),
            (str(data.get("name", "")), "#212121"),
            (str(data.get("data_date", "-")), "#2E7D32"), 
            (mcap_str, "#212121"),
            (price_str, "#212121"),
            (peak_str, "#212121"),
            (peak_diff_str, peak_diff_color),
            (ma_str, "#212121"),
            (diff_str, diff_color),
            (rsi_str, rsi_color),
            (per_str, per_color),
            (pbr_str, pbr_color)
        ]
        
        bg_color = "#FFFFFF" if row_idx % 2 == 0 else "#F9F9F9"
        
        current_row_labels = []
        
        for col_idx, (text_val, color_val) in enumerate(row_cells):
            col_info = self.col_infos[col_idx]
            lbl = tk.Label(
                self.scrollable_frame, text=text_val, bg=bg_color, fg=color_val,
                font=("맑은 고딕", 9), anchor=col_info["anchor"], padx=5, pady=4,
                wraplength=col_info["width"] - 10
            )
            lbl.grid(row=row_idx, column=col_idx, sticky="nsew")
            
            lbl.bind("<Button-1>", lambda e, r=row_idx: self.select_row(r))
            lbl.bind("<Double-1>", lambda e, sym=data["symbol"]: self.open_browser(sym))
            
            current_row_labels.append(lbl)
            
        self.row_widgets[row_idx] = current_row_labels

    def redraw_table(self):
        self.row_widgets = {} 
        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()
        for idx, data in enumerate(self.current_session_data):
            self.render_row(data, idx)

    def start_screening(self):
        if self.is_running: return
        self.is_running = True
        self.stop_requested = False
        self.current_session_data = [] 
        self.row_widgets = {}
        
        self.btn_run.config(state=tk.DISABLED)
        self.btn_load.config(state=tk.DISABLED)
        self.btn_stop.config(state=tk.NORMAL)
        
        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()
            
        market = self.market_var.get()
        top_n = int(self.top_n_var.get())
        
        threading.Thread(
            target=analyzer.screening_worker,
            args=(market, top_n, self.queue, lambda: self.stop_requested, self.opt_fundamental.get(), self.opt_peak.get(), self.us_market_cap_data),
            daemon=True
        ).start()

    def sort_by_column(self, col):
        rev = self.sort_ascending
        
        def convert_val(d):
            val = d.get(col, "")
            is_num = False
            num_val = 0.0
            
            if isinstance(val, (int, float)):
                is_num = True
                num_val = float(val)
            else:
                cleaned = re.sub(r'[^\d\.\-]', '', str(val))
                if cleaned not in ('', '-', '.', '-.'):
                    try:
                        num_val = float(cleaned)
                        is_num = True
                    except ValueError:
                        pass
            
            if is_num:
                primary = 1 if rev else 0
                return (primary, num_val)
            else:
                primary = 0 if rev else 1
                return (primary, str(val).lower())
                    
        self.current_session_data.sort(key=convert_val, reverse=rev)
        self.sort_ascending = not rev
        self.redraw_table()

    def open_browser(self, symbol):
        if self.market_var.get() == "미국":
            suffix = ".O"
            sym = symbol
            if sym == "BRK-B": sym = "BRK_B"
            try:
                ticker_info = yf.Ticker(symbol).info
                exchange = ticker_info.get('exchange', '').upper()
                if 'NYQ' in exchange or 'NYSE' in exchange: suffix = ".N"
                elif 'ASE' in exchange or 'AMEX' in exchange: suffix = ".A"
            except:
                nyse_tickers = {
                    "BRK-B", "WMT", "LLY", "JPM", "V", "XOM", "UNH", "MA", "HD", "PG",
                    "ORCL", "BAC", "CVX", "KO", "PEP", "CRM", "MCD", "IBM", "TMO", "ACN",
                    "WFC", "AXP", "GE", "NKE", "LIN", "PM", "ABT", "CAT", "TXN", "MS",
                    "DIS", "HON", "UNP", "GS", "PFE", "RTX", "LOW", "NEE", "SPGI", "COP",
                    "GEV", "LMT", "TJX", "BLK", "T", "ABBV", "GILD", "C", "BMY", "MDT",
                    "BA", "ELV", "CI", "CB", "MMC", "SYK", "DE"
                }
                if symbol in nyse_tickers: suffix = ".N"
            url = f"https://m.stock.naver.com/worldstock/stock/{sym}{suffix}/total"
        else:
            url = f"https://finance.naver.com/item/main.naver?code={symbol}"
        webbrowser.open(url)
