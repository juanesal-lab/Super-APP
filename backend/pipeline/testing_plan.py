"""📋 Plan de testeo Meta/TikTok 2026 — determinístico, $0 de APIs.

La app crea creativos por avatar/etapa, pero hasta ahora NADIE le decía a Jack CÓMO testearlos ni
cuándo matar/escalar (su flujo paso 6 era "a ojo"). Este módulo arma, a partir del manifest de un
lote (las `versions` que ya viajan con `stage`/`avatar`/`hook`), un plan concreto con los umbrales
2026 (hook rate, hold rate, CPA, muestra mínima, matar/iterar/escalar, refresh) y un NOMBRE de
anuncio copiable por versión para leer las campañas por avatar/etapa.

Todo es texto calculado en Python — CERO llamadas a IA, CERO créditos. Fuentes y detalle en
`assets/research-mejoras-2026.md`.
"""
from __future__ import annotations

import re
import unicodedata

# ── Umbrales 2026 (triangulados de breakdowns de agencias; ver research-mejoras-2026.md) ──
UMBRALES = {
    "hook_meta": (25, 35),       # % vistas 3s ÷ impresiones — bueno en Meta
    "hook_tiktok": (35, 45),     # % — bueno en TikTok
    "hold": (40, 50),            # % plays 15s ÷ vistas 3s — sano
    "hook_escala": 30,           # ≥ este % (y CPA ≤ objetivo) → escalar
    "hook_itera": 25,            # entre itera y escala → iterar cuerpo/oferta
    "cpa_itera_pct": 30,         # CPA hasta +30% del objetivo → iterar
    "cpa_mata_pct": 50,          # CPA > +50% del objetivo → matar
    "resultados_min": 50,        # compras por variante para creerle al CPA
    "dias_min": 4,               # menos de 4 días = ruido
    "gasto_mult_cpa": (1.5, 2),  # gastar 1.5-2× CPA objetivo antes de juzgar
    "gasto_mult_precio": (2, 3), # o 2-3× el precio del producto
    "creativos_min_lote": 6,     # presupuesto chico: 1 campaña amplia con 6+ creativos
    "iteraciones_por_ganador": (4, 6),  # bajo gasto
}

# Cadencia de refresh por etapa (semanas) — basado en señal, no calendario
REFRESH_SEMANAS = {"TOFU": (1, 2), "MOFU": (2, 4), "BOFU": (4, 6)}

_NOMBRES_VERSION = {
    "A_gancho": "Gancho primero", "B_narrativa": "Narrativa", "C_corta": "Corta",
    "D_dinamica": "Dinámica", "E_inversa": "Inversa", "F_express": "Express",
    "G_mixta": "Mixta", "H_alterna": "Alterna",
}


def _slug(texto: str, tope: int = 18) -> str:
    """Convierte texto a MAYÚSCULAS_SIN_ACENTOS para el nombre de anuncio (Ads Manager)."""
    if not texto:
        return ""
    t = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode("ascii")
    t = re.sub(r"[^A-Za-z0-9]+", "-", t).strip("-").upper()
    return t[:tope].strip("-")


def _ad_name(producto: str, version: dict, indice: int) -> str:
    """Nombre copiable para Ads Manager: PRODUCTO_AVATAR_ETAPA_vN (lee la cuenta por avatar/etapa)."""
    prod = _slug(producto, 14) or "PROD"
    partes = [prod]
    av = version.get("avatar")
    if av:
        partes.append(_slug(av, 16))
    st = (version.get("stage") or "").upper()
    if st in REFRESH_SEMANAS:
        partes.append(st)
    partes.append(f"v{indice + 1}")
    return "_".join(p for p in partes if p)


def generar_plan_testeo(
    versions: list[dict] | None,
    *,
    producto: str = "",
    aspect: str = "9:16",
    cpa_objetivo: float | None = None,
    precio: float | None = None,
    presupuesto_dia: float | None = None,
    moneda: str = "",
    hook_used: str = "",
) -> dict:
    """Arma el plan de testeo del lote. Devuelve dict estructurado + `markdown` copiable.

    `versions`: lista del manifest (cada una con name/stage/avatar/hook opcionales).
    `cpa_objetivo`/`precio`/`presupuesto_dia`: opcionales; si faltan, el plan da la REGLA (múltiplos)
    en vez de un número inventado — nunca inventa cifras (regla de oro de Jack).
    """
    versions = [v for v in (versions or []) if isinstance(v, dict)]
    n = len(versions)
    mon = (moneda or "").strip()
    tiktok = False   # Meta por defecto; TikTok es aditivo (mismos umbrales, hook más alto)

    # ── Filas por versión (avatar/etapa + nombre de anuncio + qué mirar) ──
    filas = []
    etapas_presentes = []
    for i, v in enumerate(versions):
        st = (v.get("stage") or "").upper()
        if st in REFRESH_SEMANAS and st not in etapas_presentes:
            etapas_presentes.append(st)
        filas.append({
            "indice": i + 1,
            "titulo": _NOMBRES_VERSION.get(v.get("name", ""), v.get("name", f"Versión {i+1}")),
            "avatar": v.get("avatar") or "",
            "estructura": v.get("estructura") or "",
            "stage": st or "",
            "hook": v.get("hook_text") or v.get("hook") or "",
            "ad_name": _ad_name(producto, v, i),
        })

    # ── Reglas de gasto/muestra (número exacto si Jack dio CPA/precio; si no, la regla) ──
    def _fmt_dinero(x: float) -> str:
        s = f"{x:,.0f}".replace(",", ".") if x >= 1000 else f"{x:g}"
        return f"{s} {mon}".strip() if mon else s

    if cpa_objetivo:
        lo, hi = UMBRALES["gasto_mult_cpa"]
        gasto_juzgar = f"{_fmt_dinero(cpa_objetivo * lo)}–{_fmt_dinero(cpa_objetivo * hi)} por variante (1.5–2× tu CPA objetivo)"
    elif precio:
        lo, hi = UMBRALES["gasto_mult_precio"]
        gasto_juzgar = f"{_fmt_dinero(precio * lo)}–{_fmt_dinero(precio * hi)} por variante (2–3× el precio del producto)"
    else:
        gasto_juzgar = "1.5–2× tu CPA objetivo (o 2–3× el precio del producto) por variante"

    cpa_txt = _fmt_dinero(cpa_objetivo) if cpa_objetivo else "tu CPA objetivo"

    plan = {
        "ok": True,
        "n_versiones": n,
        "aspect": aspect,
        "producto": producto,
        "umbrales": UMBRALES,
        "estructura_campana": {
            "tipo": "1 campaña CBO de prospecting · 1 ad set · colocaciones amplias · sin exclusiones",
            "creativos_dentro": max(UMBRALES["creativos_min_lote"], n),
            "nota_presupuesto_chico": ("Presupuesto <$100/día: 1 campaña amplia con 6+ creativos, "
                                       "toda la energía en la CALIDAD del creativo (no en micro-segmentar)."),
            "abo": "ABO SOLO para aislar un ángulo nuevo o forzar gasto a un creativo puntual.",
        },
        "senales": {
            "hook_rate": {"formula": "vistas 3s ÷ impresiones", "meta": "25–35%", "tiktok": "35–45%",
                          "lee": "primero que aparece — si el gancho es débil, se ve acá"},
            "hold_rate": {"formula": "plays 15s ÷ vistas 3s", "sano": "40–50%",
                          "lee": "si baja, el cuerpo aburre a mitad"},
            "ventana_tiktok": "señales (CTR/CPC/ATC/CPM) a 48–72h · compra real a 3–5 días",
        },
        "decision": {
            "escalar": f"hook rate ≥{UMBRALES['hook_escala']}% Y CPA ≤ {cpa_txt}",
            "iterar": f"hook rate {UMBRALES['hook_itera']}–{UMBRALES['hook_escala']}% "
                      f"o CPA hasta +{UMBRALES['cpa_itera_pct']}% del objetivo (gancho OK, cuerpo/oferta falla)",
            "matar": f"hook rate <{UMBRALES['hook_itera']}% O CPA >+{UMBRALES['cpa_mata_pct']}% del objetivo",
            "muestra_minima": f"~{UMBRALES['resultados_min']} resultados por variante o "
                              f"{UMBRALES['dias_min']}+ días (menos = ruido). Gasta {gasto_juzgar} antes de juzgar.",
            "no_matar_temprano": "Matar a las pocas horas = tirar plata y data. Aguanta la ventana mínima.",
        },
        "iteracion": {
            "por_ganador": f"{UMBRALES['iteraciones_por_ganador'][0]}–{UMBRALES['iteraciones_por_ganador'][1]} "
                           "variaciones por ganador (cambia UN eje por vez: primeros 1s, hook de texto, "
                           "orden de la demo, dureza del CTA). Un ganador = 5–10 iteraciones, no un solo ad.",
            "usa_en_app": "En la app: 🔁 Variar hook y 🎯 Clon con mi producto para las variaciones.",
        },
        "refresh": {
            "TOFU": "cada 1–2 semanas", "MOFU": "cada 2–4 semanas", "BOFU/retargeting": "cada 4–6 semanas",
            "gatillo": "solo cuando dispare la señal: frequency alta, caída de CTR o de CVR (no por calendario).",
        },
        "filas": filas,
        "avisos": [],
    }

    if presupuesto_dia:
        plan["estructura_campana"]["presupuesto_dia"] = _fmt_dinero(presupuesto_dia)
    if not cpa_objetivo and not precio:
        plan["avisos"].append("Sin CPA objetivo ni precio: el plan da las REGLAS (múltiplos), no cifras "
                              "inventadas. Pásalos para ver los montos exactos.")
    if n and n < UMBRALES["creativos_min_lote"]:
        plan["avisos"].append(f"Este lote trae {n} versiones. El mínimo sano para un test amplio es "
                             f"{UMBRALES['creativos_min_lote']} — genera más (o combina con otro lote).")
    if not etapas_presentes:
        plan["avisos"].append("Las versiones no traen etapa (TOFU/MOFU/BOFU). Con voz en off puedes "
                             "activar el embudo para diversificar ángulos y leer mejor la cuenta.")

    plan["markdown"] = _a_markdown(plan)
    return plan


def _a_markdown(plan: dict) -> str:
    """Render legible/copiable (para el modal del front y para descargar)."""
    L: list[str] = []
    L.append(f"# 📋 Plan de testeo Meta/TikTok 2026 — {plan['n_versiones']} versiones ({plan['aspect']})")
    if plan.get("producto"):
        L.append(f"**Producto:** {plan['producto']}")
    L.append("")
    ec = plan["estructura_campana"]
    L.append("## 1) Montaje de campaña")
    L.append(f"- {ec['tipo']}")
    L.append(f"- Mete **{ec['creativos_dentro']}+ creativos** en el mismo ad set.")
    if ec.get("presupuesto_dia"):
        L.append(f"- Presupuesto: **{ec['presupuesto_dia']}/día**.")
    L.append(f"- {ec['nota_presupuesto_chico']}")
    L.append(f"- {ec['abo']}")
    L.append("")
    L.append("## 2) Señales tempranas (en este orden)")
    s = plan["senales"]
    L.append(f"1. **Hook rate** ({s['hook_rate']['formula']}) — Meta {s['hook_rate']['meta']}, "
             f"TikTok {s['hook_rate']['tiktok']}. {s['hook_rate']['lee']}.")
    L.append(f"2. **Hold rate** ({s['hold_rate']['formula']}) — sano {s['hold_rate']['sano']}. "
             f"{s['hold_rate']['lee']}.")
    L.append(f"3. TikTok: {s['ventana_tiktok']}.")
    L.append("")
    d = plan["decision"]
    L.append("## 3) Matar / Iterar / Escalar")
    L.append(f"- 🟢 **Escalar:** {d['escalar']}")
    L.append(f"- 🟡 **Iterar:** {d['iterar']}")
    L.append(f"- 🔴 **Matar:** {d['matar']}")
    L.append(f"- ⏳ **Muestra mínima:** {d['muestra_minima']}")
    L.append(f"- ⚠️ {d['no_matar_temprano']}")
    L.append("")
    it = plan["iteracion"]
    L.append("## 4) Cuando algo gana")
    L.append(f"- {it['por_ganador']}")
    L.append(f"- {it['usa_en_app']}")
    L.append("")
    rf = plan["refresh"]
    L.append("## 5) Refresh / fatiga")
    L.append(f"- TOFU {rf['TOFU']} · MOFU {rf['MOFU']} · BOFU/retargeting {rf['BOFU/retargeting']}.")
    L.append(f"- {rf['gatillo']}")
    L.append("")
    if plan["filas"]:
        L.append("## 6) Tus versiones (nómbralas así en Ads Manager)")
        for f in plan["filas"]:
            etq = " · ".join(x for x in [f["stage"], f["avatar"]] if x)
            extra = f" — {etq}" if etq else ""
            L.append(f"- `{f['ad_name']}` — {f['titulo']}{extra}")
            if f["hook"]:
                L.append(f"    - Hook: “{f['hook']}”")
    if plan["avisos"]:
        L.append("")
        L.append("## ⚠️ Avisos")
        for a in plan["avisos"]:
            L.append(f"- {a}")
    return "\n".join(L)
