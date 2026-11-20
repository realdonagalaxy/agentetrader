"""Gestione Conti come APPLICAZIONE DESKTOP: la stessa interfaccia in una finestra del programma (pywebview), senza browser.
Avvia da solo il server locale e l'ascolto dei segnali; chiudendo la finestra chiede se ridurre l'app nell'area di notifica (i segnali restano attivi) o chiudere tutto.

  .venv\\Scripts\\pythonw.exe -m src.desktop_app            (senza finestra nera; errori in journal/desktop.log)
  .venv\\Scripts\\python.exe  -m src.desktop_app --nascosto  (parte ridotta nell'area di notifica)

Se pywebview non è installato apre il browser come prima. Per tornare alla versione solo-web: ramo git backup-webapp-2026-11-20."""
import os
import sys
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

TITLE = "Gestione Conti — donatrader"
ICON = ROOT / "src" / "web" / "app.ico"
LOGO = ROOT / "src" / "web" / "favicon.png"

if sys.stdout is None or sys.stderr is None:                       # pythonw: nessuna console, il registro va su file
    (ROOT / "journal").mkdir(exist_ok=True)
    _log = open(ROOT / "journal" / "desktop.log", "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stdout or _log
    sys.stderr = sys.stderr or _log

state = {"quit": False, "window": None, "tray": None, "owns_server": False}

CLOSE_DIALOG_JS = """
(function(){
  if (document.getElementById('gc-close')) return;
  const d = document.createElement('div'); d.id = 'gc-close';
  d.style.cssText = 'position:fixed;inset:0;background:rgba(10,17,27,.6);z-index:99999;display:flex;align-items:center;justify-content:center;font:14px Segoe UI,system-ui,sans-serif';
  d.innerHTML = `<div style="background:#fff;color:#14202e;border-radius:10px;width:min(470px,92vw);padding:20px 22px;box-shadow:0 20px 60px rgba(0,0,0,.6)">
    <h3 style="margin:0 0 8px;font-size:17px">Chiudere la finestra?</h3>
    <p style="margin:0 0 14px;color:#41505f;line-height:1.5">L'ascolto dei segnali di Telegram e il controllo del pareggio (BE) dopo TP1 lavorano in background.</p>
    <div style="display:grid;gap:8px">
      <button id="gc-hide" style="font:inherit;padding:10px 14px;border-radius:6px;border:1px solid #14233a;background:#14233a;color:#fff;text-align:left;cursor:pointer;font-weight:600">__HIDE__<small style="display:block;font-weight:400;color:#b8c6dc;margin-top:2px">Consigliato: i segnali restano attivi</small></button>
      <button id="gc-quit" style="font:inherit;padding:10px 14px;border-radius:6px;border:1px solid #d9dfe6;background:#fff;color:#14202e;text-align:left;cursor:pointer">Chiudi tutto<small style="display:block;color:#667483;margin-top:2px">Ferma anche l'ascolto dei segnali: nessun segnale verrà aperto finché non riapri il programma</small></button>
      <button id="gc-no" style="font:inherit;padding:10px 14px;border-radius:6px;border:1px solid #d9dfe6;background:#fff;color:#14202e;text-align:left;cursor:pointer">Annulla</button>
    </div></div>`;
  document.body.appendChild(d);
  const close = () => d.remove();
  document.getElementById('gc-hide').onclick = () => { close(); pywebview.api.hide(); };
  document.getElementById('gc-quit').onclick = () => { pywebview.api.quit_all(); };
  document.getElementById('gc-no').onclick = close;
})();
"""


def single_instance() -> bool:
    """Una sola app alla volta (blocco del sistema operativo)."""
    (ROOT / "journal").mkdir(exist_ok=True)
    f = open(ROOT / "journal" / "desktop.lock", "a+")
    try:
        if os.name == "nt":
            import msvcrt
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return False
    state["lock"] = f
    return True


def existing_server() -> str:
    """URL di un Gestione Conti già in esecuzione sulla porta predefinita (avviato con il .bat): in quel caso la finestra si collega a quello."""
    try:
        with urllib.request.urlopen("http://127.0.0.1:8080/", timeout=2) as r:
            if b"Gestione Conti" in r.read(200000):
                return "http://127.0.0.1:8080"
    except Exception:
        pass
    return ""


def start_server() -> str:
    """Avvia il server di Gestione Conti in un thread (parte anche l'ascolto dei segnali) e restituisce l'URL."""
    url = existing_server()
    if url:
        print("Gestione Conti già in esecuzione: mi collego a quello.", flush=True)
        return url
    from src import accounts_web
    ready = threading.Event()
    box: dict = {}

    def on_ready(u):
        box["url"] = u
        ready.set()

    def run():
        try:
            accounts_web.main(["--no-browser"], on_ready=on_ready)
        except SystemExit as e:
            box["err"] = str(e.code or "Gestione Conti si è fermato")
            ready.set()
        except Exception as e:
            box["err"] = f"{type(e).__name__}: {e}"
            ready.set()

    threading.Thread(target=run, daemon=True).start()
    if not ready.wait(90) or "url" not in box:
        raise RuntimeError(box.get("err") or "Il server di Gestione Conti non è partito entro 90 secondi.")
    state["owns_server"] = True
    return box["url"]


def stop_everything() -> None:
    """Chiudi tutto: ferma l'ascolto dei segnali (solo se il server è nostro) e il server."""
    try:
        from src import accounts_web
        if state["owns_server"]:
            accounts_web.kill_listeners()
            if accounts_web.SRV is not None:
                threading.Thread(target=accounts_web.SRV.shutdown, daemon=True).start()
    except Exception as e:
        print("Chiusura:", str(e)[:150], flush=True)


class Api:
    """Funzioni chiamate dalla pagina (pulsanti del dialogo di chiusura)."""

    def hide(self):
        w = state["window"]
        if state["tray"] is not None:
            w.hide()                                       # resta l'icona nell'area di notifica
        else:
            w.minimize()                                   # senza icona (pystray assente) si riduce nella barra delle applicazioni

    def quit_all(self):
        state["quit"] = True
        stop_everything()
        t = state["tray"]
        if t is not None:
            try:
                t.stop()
            except Exception:
                pass
        state["window"].destroy()


def on_closing():
    if state["quit"]:
        return True
    w = state["window"]
    hide_label = "Riduci nell'area di notifica" if state["tray"] is not None else "Riduci nella barra delle applicazioni"
    threading.Thread(target=lambda: w.evaluate_js(CLOSE_DIALOG_JS.replace("__HIDE__", hide_label)), daemon=True).start()   # in un thread: dall'evento di chiusura si rischierebbe di bloccare la finestra
    return False                                           # la finestra resta: decide l'utente dal dialogo


def set_window_icon() -> None:
    """Icona della finestra e della barra delle applicazioni (Windows): pywebview non la imposta da solo."""
    if os.name != "nt" or not ICON.exists():
        return
    try:
        import ctypes
        u = ctypes.windll.user32
        hwnd = u.FindWindowW(None, TITLE)
        for size, which in ((16, 0), (32, 1)):
            h = u.LoadImageW(None, str(ICON), 1, size, size, 0x10)       # IMAGE_ICON, LR_LOADFROMFILE
            u.SendMessageW(hwnd, 0x80, which, h)                        # WM_SETICON
    except Exception as e:
        print("Icona finestra:", e, flush=True)


def build_tray():
    """Icona nell'area di notifica (pystray). None se la libreria manca."""
    try:
        import pystray
        from PIL import Image
    except ImportError:
        return None
    from src import accounts_web

    def running():
        try:
            return accounts_web.listener_running()
        except Exception:
            return False

    def show(*_):
        state["window"].show()

    def toggle_signals(*_):
        try:
            if running():
                accounts_web.listener_stop()
            else:
                accounts_web.listener_start()
        except Exception as e:
            print("Segnali:", str(e)[:150], flush=True)

    def open_log(*_):
        p = ROOT / "journal" / "mt5_orders.log"
        if os.name == "nt" and p.exists():
            os.startfile(str(p))

    def quit_(*_):
        Api().quit_all()

    menu = pystray.Menu(
        pystray.MenuItem(lambda i: "● Ascolto segnali: " + ("attivo" if running() else "fermo"), None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Apri Gestione Conti", show, default=True),
        pystray.MenuItem(lambda i: "Metti in pausa i segnali" if running() else "Riattiva i segnali", toggle_signals),
        pystray.MenuItem("Apri il registro", open_log),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Esci e ferma tutto", quit_),
    )
    icon = pystray.Icon("gestione_conti", Image.open(LOGO), "Gestione Conti", menu)
    icon.run_detached()
    return icon


def main() -> None:
    hidden = "--nascosto" in sys.argv
    if not single_instance():
        print("Gestione Conti desktop è già aperto.", flush=True)
        return
    try:
        import webview
    except ImportError:
        webview = None
    try:
        url = start_server()
    except Exception as e:
        print("ERRORE:", e, flush=True)
        if os.name == "nt":
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, f"Gestione Conti non è partito:\n\n{e}", TITLE, 0x10)
        return
    if webview is None:
        print("pywebview non installato (pip install pywebview): apro il browser.", flush=True)
        import webbrowser
        webbrowser.open(url)
        while True:
            time.sleep(3600)
    state["tray"] = build_tray()
    w = webview.create_window(TITLE, url, width=1280, height=860, min_size=(900, 600), js_api=Api(), hidden=hidden and state["tray"] is not None, text_select=True)
    state["window"] = w
    w.events.closing += on_closing
    w.events.shown += lambda: threading.Timer(0.8, set_window_icon).start()
    webview.start(icon=str(ICON) if ICON.exists() else None)
    stop_everything() if state["quit"] else None


if __name__ == "__main__":
    main()
