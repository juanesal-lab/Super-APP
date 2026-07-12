"""Notificaciones a Telegram: manda el video final cuando un proyecto termina de montarse.

Reusa el mismo bot que Comando Vidaria. Llaves en .env (cargadas con dotenv al arrancar):
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
Si no están configuradas, no hace nada (falla en silencio). El envío corre en su propio
try/except para que un fallo de red NUNCA rompa el pipeline de render.
"""
from __future__ import annotations

import os
from pathlib import Path

import requests

LIMITE_MB = 50  # tope de subida del Bot API estándar de Telegram


def _cfg() -> tuple[str | None, str | None]:
    return os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")


def _url(token: str, metodo: str) -> str:
    return f"https://api.telegram.org/bot{token}/{metodo}"


def enviar_texto(texto: str) -> None:
    token, chat_id = _cfg()
    if not token or not chat_id:
        return
    try:
        requests.post(_url(token, "sendMessage"),
                      json={"chat_id": chat_id, "text": texto[:4000], "parse_mode": "Markdown"},
                      timeout=20)
    except Exception:  # noqa: BLE001
        pass


def enviar_video(path, caption: str = "") -> dict:
    """Sube un video a Telegram. Si pesa más de 50MB avisa por texto con la ruta local.
    Devuelve {ok, error}. Nunca lanza excepción."""
    token, chat_id = _cfg()
    if not token or not chat_id:
        return {"ok": False, "error": "Telegram no configurado"}
    p = Path(path)
    if not p.exists():
        return {"ok": False, "error": f"no existe: {p}"}
    mb = p.stat().st_size / 1_000_000
    if mb > LIMITE_MB:
        enviar_texto(f"🎬 *{caption or p.name}* quedó listo, pero pesa {mb:.0f}MB "
                     f"(Telegram no deja subir >{LIMITE_MB}MB por bot).\nEstá en:\n`{p}`")
        return {"ok": False, "error": f"muy grande ({mb:.0f}MB)"}
    try:
        with open(p, "rb") as f:
            r = requests.post(_url(token, "sendVideo"),
                              data={"chat_id": chat_id, "caption": caption[:1000],
                                    "supports_streaming": "true"},
                              files={"video": (p.name, f, "video/mp4")}, timeout=600)
        if r.status_code == 200:
            return {"ok": True, "error": None}
        # Fallback: mandarlo como documento (a veces Telegram rechaza el sendVideo por formato)
        with open(p, "rb") as f:
            r2 = requests.post(_url(token, "sendDocument"),
                               data={"chat_id": chat_id, "caption": caption[:1000]},
                               files={"document": (p.name, f, "video/mp4")}, timeout=600)
        return {"ok": r2.status_code == 200,
                "error": None if r2.status_code == 200 else r2.text[:150]}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)[:150]}


def enviar_resultado(pdir, nombre: str, videos: list[str]) -> None:
    """Manda a Telegram los videos finales de un proyecto ya terminado.
    `pdir` es la carpeta del proyecto; `videos` son rutas relativas a resultado/."""
    token, chat_id = _cfg()
    if not token or not chat_id:
        return
    pdir = Path(pdir)
    enviados = 0
    for rel in videos:
        vp = pdir / "resultado" / rel
        if vp.exists():
            cap = f"🎬 {nombre} — {rel}" if enviados == 0 else rel
            res = enviar_video(vp, caption=cap)
            if res.get("ok"):
                enviados += 1
    if enviados == 0:
        enviar_texto(f"✅ *{nombre}* terminó de montarse (revisa la app; no pude enviar el video por Telegram).")
