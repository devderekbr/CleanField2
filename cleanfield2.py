import tkinter as tk
from tkinter import messagebox
import threading
import json
import os
import re
import time

try:
    import pyperclip
except ImportError:
    import subprocess
    subprocess.check_call(["pip", "install", "pyperclip", "--break-system-packages"])
    import pyperclip

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "masks.json")

BG         = "#1a1a1a"
SECTION_BG = "#2a2a2a"
BORDER     = "#3a3a3a"
FG         = "#f0f0f0"
FG_DIM     = "#888888"
FG_LABEL   = "#cccccc"
BLUE       = "#1e6eb5"
BLUE_HV    = "#2481d0"
GREEN      = "#1e7e34"
GREEN_HV   = "#28a745"
RED        = "#c0392b"
RED_HV     = "#e74c3c"
ENTRY_BG   = "#2a2a2a"
ENTRY_FG   = "#f0f0f0"
TITLE_FG   = "#ffffff"
LOG_BG     = "#111111"
LOG_ARROW  = "#555555"
LOG_ORIG   = "#666666"
LOG_FMT    = "#e0e0e0"
LOG_HOVER  = "#2a2a2a"
MAX_LOG    = 20


def load_masks():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return [
        {"mask": "000-000-000",        "enabled": True},
        {"mask": "00.000.000/0000-00", "enabled": False},
    ]


def save_masks(masks):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(masks, f, ensure_ascii=False, indent=2)


def count_zeros(mask):
    return mask.count("0")


def apply_mask(digits, mask):
    if len(digits) != count_zeros(mask):
        return None
    result, idx = [], 0
    for ch in mask:
        if ch == "0":
            result.append(digits[idx])
            idx += 1
        else:
            result.append(ch)
    return "".join(result)


def setup_mousewheel(root):
    def _on_wheel(event):
        widget = event.widget
        while widget:
            if isinstance(widget, tk.Canvas):
                widget.yview_scroll(int(-1 * (event.delta / 120)), "units")
                return
            try:
                widget = widget.master
            except Exception:
                break
    root.bind_all("<MouseWheel>", _on_wheel)


class ClipboardFormatterApp:
    def __init__(self, root):
        self.root = root
        self.root.title("CleanField 2")
        self.root.geometry("620x490")
        self.root.minsize(620, 490)
        self.root.configure(bg=BG)
        self.root.resizable(True, True)

        self.masks = load_masks()
        self._last_clip = ""
        self._writing = False
        self._mask_widgets = []
        self._log_entries = []      # lista de (original, formatado)
        self._log_labels  = []      # widgets da sidebar

        self._build_ui()
        setup_mousewheel(self.root)
        self._start_monitor()

    # ── UI ────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        # divide a janela: painel principal (esq) + sidebar (dir)
        self.pane = tk.Frame(self.root, bg=BG)
        self.pane.pack(fill="both", expand=True)

        self._build_main(self.pane)
        self._build_sidebar(self.pane)

    def _build_main(self, parent):
        main = tk.Frame(parent, bg=BG)
        main.pack(side="left", fill="both", expand=True)

        # título
        titulo_frame = tk.Frame(main, bg=BG)
        titulo_frame.pack(pady=(18, 4))
        tk.Label(titulo_frame, text="CleanField ",
                 font=("Segoe UI", 22, "bold"), bg=BG, fg=TITLE_FG
                 ).pack(side="left", pady=(10, 0))
        tk.Label(titulo_frame, text="2",
                 font=("Segoe UI", 34, "bold"), bg=BG, fg="#FFD700"
                 ).pack(side="left")

        # status
        status_row = tk.Frame(main, bg=BG)
        status_row.pack(fill="x", padx=20, pady=(0, 8))
        self.status_dot = tk.Label(status_row, text="●",
                                   font=("Segoe UI", 10), bg=BG, fg=GREEN)
        self.status_dot.pack(side="left")
        tk.Label(status_row, text=" monitorando área de transferência",
                 font=("Segoe UI", 9), bg=BG, fg=FG_DIM).pack(side="left")

        tk.Frame(main, bg=BORDER, height=1).pack(fill="x", padx=16)

        # lista scrollável
        list_frame = tk.Frame(main, bg=BG)
        list_frame.pack(fill="both", expand=True, pady=4)

        self.main_canvas = tk.Canvas(list_frame, bg=BG, highlightthickness=0, bd=0)
        vsb = tk.Scrollbar(list_frame, orient="vertical",
                           command=self.main_canvas.yview)
        self.list_container = tk.Frame(self.main_canvas, bg=BG)

        win_id = self.main_canvas.create_window(
            (0, 0), window=self.list_container, anchor="nw")
        self.main_canvas.configure(yscrollcommand=vsb.set)

        self.list_container.bind("<Configure>", lambda e:
            self.main_canvas.configure(
                scrollregion=self.main_canvas.bbox("all")))
        self.main_canvas.bind("<Configure>", lambda e:
            self.main_canvas.itemconfig(win_id, width=e.width))

        self.main_canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        self._rebuild_list()

        tk.Frame(main, bg=BORDER, height=1).pack(fill="x", padx=16)

        tk.Button(main, text="+ Adicionar Formatação",
                  font=("Segoe UI", 11, "bold"),
                  bg=BLUE, fg=FG, relief="flat", bd=0,
                  activebackground=BLUE_HV, activeforeground=FG,
                  cursor="hand2", command=self._open_add_popup
                  ).pack(fill="x", padx=16, pady=12, ipady=8)

    def _build_sidebar(self, parent):
        # divisor vertical
        tk.Frame(parent, bg=BORDER, width=1).pack(side="left", fill="y")

        sidebar = tk.Frame(parent, bg=LOG_BG, width=220)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        tk.Label(sidebar, text="Histórico",
                 font=("Segoe UI", 10, "bold"),
                 bg=LOG_BG, fg=FG_DIM).pack(pady=(12, 4), padx=12, anchor="w")
        tk.Frame(sidebar, bg=BORDER, height=1).pack(fill="x", padx=0)

        # canvas scrollável para os itens do log
        self.log_canvas = tk.Canvas(sidebar, bg=LOG_BG,
                                    highlightthickness=0, bd=0)
        log_vsb = tk.Scrollbar(sidebar, orient="vertical",
                               command=self.log_canvas.yview)
        self.log_inner = tk.Frame(self.log_canvas, bg=LOG_BG)

        log_win = self.log_canvas.create_window(
            (0, 0), window=self.log_inner, anchor="nw")
        self.log_canvas.configure(yscrollcommand=log_vsb.set)

        self.log_inner.bind("<Configure>", lambda e:
            self.log_canvas.configure(
                scrollregion=self.log_canvas.bbox("all")))
        self.log_canvas.bind("<Configure>", lambda e:
            self.log_canvas.itemconfig(log_win, width=e.width))

        self.log_canvas.pack(side="left", fill="both", expand=True)
        log_vsb.pack(side="right", fill="y")

    # ── log ───────────────────────────────────────────────────────────────────
    def _add_log(self, original, formatted):

        # evita repetição consecutiva
        if self._log_entries and self._log_entries[0] == (original, formatted):
            return

        self._log_entries.insert(0, (original, formatted))

        if len(self._log_entries) > MAX_LOG:
            self._log_entries.pop()

        self._refresh_log()

    def _refresh_log(self):
        for w in self.log_inner.winfo_children():
            w.destroy()
        self._log_labels.clear()

        for original, formatted in self._log_entries:
            self._make_log_row(original, formatted)

    def _make_log_row(self, original, formatted):
        row = tk.Frame(self.log_inner, bg=LOG_BG, cursor="hand2")
        row.pack(fill="x", padx=0, pady=0)

        # linha formatada (destaque)
        fmt_lbl = tk.Label(row,
                           text=formatted,
                           font=("Consolas", 9, "bold"),
                           bg=LOG_BG, fg=LOG_FMT,
                           anchor="w", padx=10, pady=4)
        fmt_lbl.pack(fill="x")

        # linha original com seta
        orig_lbl = tk.Label(row,
                            text=f"  ← {original}",
                            font=("Consolas", 8),
                            bg=LOG_BG, fg=LOG_ORIG,
                            anchor="w", padx=10, pady=0)
        orig_lbl.pack(fill="x")

        # separador leve
        tk.Frame(row, bg=BORDER, height=1).pack(fill="x")

        # hover: destaca a linha
        def on_enter(e, r=row, f=fmt_lbl, o=orig_lbl):
            r.config(bg=LOG_HOVER)
            f.config(bg=LOG_HOVER)
            o.config(bg=LOG_HOVER)

        def on_leave(e, r=row, f=fmt_lbl, o=orig_lbl):
            r.config(bg=LOG_BG)
            f.config(bg=LOG_BG)
            o.config(bg=LOG_BG)

        # clique copia o valor formatado para o clipboard
        def on_click(e, val=formatted):
            self._writing = True
            pyperclip.copy(val)
            self._last_clip = val
            time.sleep(0.05)
            self._writing = False

        for w in (row, fmt_lbl, orig_lbl):
            w.bind("<Enter>",   on_enter)
            w.bind("<Leave>",   on_leave)
            w.bind("<Button-1>", on_click)

        self._log_labels.append(row)

    # ── lista principal ───────────────────────────────────────────────────────
    def _rebuild_list(self):
        for w in self.list_container.winfo_children():
            w.destroy()
        self._mask_widgets.clear()
        for idx, m in enumerate(self.masks):
            self._add_row_widget(idx, m)

    def _add_row_widget(self, idx, m):
        tk.Label(self.list_container,
                 text=f"{idx + 1} -  {m['mask']}",
                 font=("Segoe UI", 10, "bold"),
                 bg=BG, fg=FG_LABEL
                 ).pack(anchor="w", padx=16, pady=(10, 0))

        card = tk.Frame(self.list_container, bg=SECTION_BG,
                        highlightbackground=BORDER, highlightthickness=1)
        card.pack(fill="x", padx=16, pady=(3, 0))

        toggle_btn = tk.Button(card, font=("Segoe UI", 10, "bold"),
                               relief="flat", bd=0, cursor="hand2",
                               padx=16, pady=6)
        toggle_btn.pack(side="left", padx=10, pady=8)
        self._apply_toggle_style(toggle_btn, m["enabled"])
        toggle_btn.config(command=lambda i=idx, b=toggle_btn: self._toggle(i, b))

        tk.Button(card, text="✕ Remover",
                  font=("Segoe UI", 9),
                  bg=SECTION_BG, fg=FG_DIM, relief="flat", bd=0,
                  activebackground=RED, activeforeground=FG,
                  cursor="hand2",
                  command=lambda i=idx: self._delete_mask(i)
                  ).pack(side="right", padx=10)

        self._mask_widgets.append({"btn": toggle_btn})

    def _apply_toggle_style(self, btn, enabled):
        if enabled:
            btn.config(text="ATIVADO", bg=GREEN, fg=FG,
                       activebackground=GREEN_HV, activeforeground=FG)
        else:
            btn.config(text="DESATIVADO", bg=RED, fg=FG,
                       activebackground=RED_HV, activeforeground=FG)

    # ── popup ─────────────────────────────────────────────────────────────────
    def _open_add_popup(self):
        PRESETS = [
            ("Cod. Suporte",      "000-000-000"),
            ("CNPJ Limpo",        "00000000000000"),
            ("CPF Limpo",         "00000000000"),
            ("Celular Limpo",     "00000000000"),
            ("Telefone Limpo",    "0000000000"),

            ("CNPJ Completo",     "00.000.000/0000-00"),
            ("CPF Completo",      "000.000.000-00"),
            ("Celular Completo",  "(00) 00000-0000"),
            ("Telefone Completo", "(00) 0000-0000"),
            
        ]

        popup = tk.Toplevel(self.root)
        popup.title("Adicionar Formatação")
        popup.configure(bg=BG)
        popup.resizable(False, True)
        popup.grab_set()

        self.root.update_idletasks()
        pw, ph = 390, 560
        rx = self.root.winfo_rootx() + (self.root.winfo_width()  - pw) // 2
        ry = self.root.winfo_rooty() + (self.root.winfo_height() - ph) // 2
        popup.geometry(f"{pw}x{ph}+{rx}+{ry}")

        tk.Label(popup, text="Adicionar Formatação",
                 font=("Segoe UI", 14, "bold"),
                 bg=BG, fg=TITLE_FG).pack(pady=(14, 4))
        tk.Frame(popup, bg=BORDER, height=1).pack(fill="x", padx=16, pady=(0, 4))

        canvas_frame = tk.Frame(popup, bg=BG)
        canvas_frame.pack(fill="both", expand=True)

        popup_canvas = tk.Canvas(canvas_frame, bg=BG, highlightthickness=0, bd=0)
        popup_vsb = tk.Scrollbar(canvas_frame, orient="vertical",
                                 command=popup_canvas.yview)
        inner = tk.Frame(popup_canvas, bg=BG)

        win_id = popup_canvas.create_window((0, 0), window=inner, anchor="nw")
        popup_canvas.configure(yscrollcommand=popup_vsb.set)

        inner.bind("<Configure>", lambda e: popup_canvas.configure(
            scrollregion=popup_canvas.bbox("all")))
        popup_canvas.bind("<Configure>", lambda e: popup_canvas.itemconfig(
            win_id, width=e.width))

        popup_canvas.pack(side="left", fill="both", expand=True)
        popup_vsb.pack(side="right", fill="y")

        for i, (label, mask) in enumerate(PRESETS, 1):
            already = any(m["mask"] == mask for m in self.masks)

            tk.Label(inner, text=f"{i} -  {label}",
                     font=("Segoe UI", 9, "bold"),
                     bg=BG, fg=FG_LABEL
                     ).pack(anchor="w", padx=16, pady=(10, 0))

            card = tk.Frame(inner, bg=SECTION_BG,
                            highlightbackground=BORDER, highlightthickness=1)
            card.pack(fill="x", padx=16, pady=(3, 0))

            tk.Label(card, text=mask, font=("Consolas", 10),
                     bg=SECTION_BG, fg=FG_DIM).pack(side="left", padx=10, pady=8)

            if already:
                tk.Label(card, text="já adicionado",
                         font=("Segoe UI", 8), bg=SECTION_BG, fg=FG_DIM
                         ).pack(side="right", padx=10)
            else:
                tk.Button(card, text="ADICIONAR",
                          font=("Segoe UI", 9, "bold"),
                          bg=BLUE, fg=FG, relief="flat", bd=0,
                          activebackground=BLUE_HV, activeforeground=FG,
                          cursor="hand2", padx=10, pady=4,
                          command=lambda m=mask, p=popup: self._add_preset(m, p)
                          ).pack(side="right", padx=10, pady=6)

        tk.Frame(popup, bg=BORDER, height=1).pack(fill="x", padx=16, pady=(8, 4))
        tk.Label(popup, text="Personalizada (use 0 para cada dígito):",
                 font=("Segoe UI", 9, "bold"), bg=BG, fg=FG_LABEL
                 ).pack(padx=16, anchor="w")

        custom_row = tk.Frame(popup, bg=BG)
        custom_row.pack(fill="x", padx=16, pady=(4, 14))

        custom_var = tk.StringVar()
        custom_entry = tk.Entry(custom_row, textvariable=custom_var,
                                font=("Consolas", 11), bg=ENTRY_BG, fg=ENTRY_FG,
                                insertbackground=ENTRY_FG, relief="flat", bd=0)
        custom_entry.pack(side="left", fill="x", expand=True, ipady=7, padx=(0, 8))

        def do_custom():
            mask = custom_var.get().strip()
            if not mask:
                return
            if count_zeros(mask) == 0:
                messagebox.showwarning("Inválida",
                                       "Use '0' para cada dígito. Ex: 000-000",
                                       parent=popup)
                return
            self._add_preset(mask, popup)

        custom_entry.bind("<Return>", lambda e: do_custom())
        tk.Button(custom_row, text="ADICIONAR",
                  font=("Segoe UI", 9, "bold"),
                  bg=BLUE, fg=FG, relief="flat", bd=0,
                  activebackground=BLUE_HV, cursor="hand2",
                  command=do_custom).pack(side="right", ipady=6)

        setup_mousewheel(popup)

    def _add_preset(self, mask, popup):
        if any(m["mask"] == mask for m in self.masks):
            messagebox.showinfo("Aviso", "Essa máscara já existe.", parent=popup)
            return
        new = {"mask": mask, "enabled": True}
        self.masks.append(new)
        save_masks(self.masks)
        self._add_row_widget(len(self.masks) - 1, new)
        popup.destroy()

    # ── ações ─────────────────────────────────────────────────────────────────
    def _toggle(self, idx, btn):
        self.masks[idx]["enabled"] = not self.masks[idx]["enabled"]
        self._apply_toggle_style(btn, self.masks[idx]["enabled"])
        save_masks(self.masks)
        try:
            current = pyperclip.paste()
            if current:
                self._last_clip = ""
                self._process(current)
                self._last_clip = pyperclip.paste()
        except Exception:
            pass

    def _delete_mask(self, idx):
        self.masks.pop(idx)
        save_masks(self.masks)
        self._rebuild_list()

    # ── monitor ───────────────────────────────────────────────────────────────
    def _start_monitor(self):
        threading.Thread(target=self._monitor_loop, daemon=True).start()

    def _monitor_loop(self):
        try:
            current = pyperclip.paste()
            if current:
                self._process(current)
                self._last_clip = pyperclip.paste()
        except Exception:
            pass
        while True:
            try:
                clip = pyperclip.paste()
                if clip != self._last_clip and not self._writing:
                    self._last_clip = clip
                    self._process(clip)
            except Exception:
                pass
            time.sleep(0.3)

    def _process(self, text):
        digits = re.sub(r"\D", "", text)
        if not digits:
            return
        if re.search(r"[A-Za-z]", text.strip()):
            return
        for m in self.masks:
            if not m["enabled"]:
                continue
            if count_zeros(m["mask"]) == len(digits):
                formatted = apply_mask(digits, m["mask"])
                if formatted and (formatted != text or text == digits):
                    self._writing = True
                    pyperclip.copy(formatted)
                    self._last_clip = formatted
                    time.sleep(0.1)
                    self._writing = False
                    # registra no log (na thread principal via after)
                    self.root.after(0, self._add_log, text, formatted)
                break


if __name__ == "__main__":
    root = tk.Tk()
    app = ClipboardFormatterApp(root)
    root.mainloop()
