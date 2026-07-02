"""Motor de VARIACIÓN de un creativo ganador (creative scaling) — parte de HOOK + VOZ + COPY.

De UN creativo VALIDADO saca N variaciones que MANTIENEN el arco/concepto que ya funciona, pero varían:
  - el HOOK (0-3s, la palanca más alta),
  - el GUION de voz en off (mismo arco, otras palabras),
  - el COPY en pantalla (subtítulos/gancho).
Y, para el modo "hook + tomas", entrega un BRIEF de qué ESCENA buscar por fase (el puente hacia el motor de
VIDEO/escenas que arma Ángel: con ese brief, tiktok_search busca la toma y assemble la empalma).

Este módulo NO toca video — solo produce los ASSETS de guion/hook/copy + el brief de escenas. Cerebro: Claude.
"""
from __future__ import annotations

_CLAUDE = "claude-opus-4-8"

_SISTEMA = """Eres un experto en CREATIVE SCALING de ads de dropshipping (Colombia, español colombiano, tuteo).
Te doy un creativo GANADOR ya VALIDADO (su arco/guion) + el producto. Tu trabajo: sacar N variaciones que
CONSERVAN el concepto y el arco que YA funciona (HOOK → DOLOR → SOLUCIÓN/PRODUCTO → DESEO/PRUEBA → CTA), pero
VARÍAN lo de arriba para que Meta las vea como creativos NUEVOS (mata el ad-fatigue y el detector de duplicados).

Qué varías en cada variación:
- HOOK (0-3s): un gancho DISTINTO y potente — pregunta, dato de shock, confesión, curiosidad, escena. Es lo
  que más mueve el rendimiento; hazlos MUY diferentes entre sí.
- GUION de voz en off: reescribe el mensaje con OTRAS palabras y otro tono, pero respetando el arco y el
  beneficio real. Español colombiano, natural, hablado (no acartonado).
- COPY en pantalla: el texto/subtítulo gancho corto que iría encima del video.
- El CTA SIEMPRE cierra pidiendo el pedido (contraentrega), sin decir precio ni cifras.

Para el modo con TOMAS: además, por cada FASE del arco dime qué TIPO de escena buscar para REEMPLAZAR la toma
original (así el video queda ~80% nuevo). Descríbelo como se BUSCARÍA en TikTok: corto y concreto
(ej. "primer plano de mujer frustrada frente al espejo", "manos aplicando crema", "antes/después de piel").

REGLAS: nada de precio ni % médicos (usa "ayuda a / apoya"). Mantén el producto y el dolor reales del ganador.
Variedad obligatoria: los N hooks deben ser MUY distintos entre sí (no 3 versiones de lo mismo)."""

_TOOL = {
    "name": "entregar_variaciones",
    "description": "Entrega las N variaciones (hook + guion + copy + brief de escenas) del creativo ganador.",
    "input_schema": {
        "type": "object",
        "properties": {
            "variaciones": {
                "type": "array",
                "description": "N variaciones MUY distintas entre sí, todas sobre el mismo arco validado.",
                "items": {
                    "type": "object",
                    "properties": {
                        "hook": {"type": "string", "description": "el gancho 0-3s (español colombiano, corto, fuerte)"},
                        "angulo": {"type": "string", "description": "nombre corto del ángulo/gancho psicológico"},
                        "guion": {"type": "string", "description": "guion de voz en off completo (mismo arco, otras palabras). Cierra pidiendo el pedido contraentrega, sin precio."},
                        "copy_pantalla": {"type": "string", "description": "texto/subtítulo gancho corto para encima del video"},
                        "escenas": {
                            "type": "array",
                            "description": "SOLO si se piden tomas: qué escena buscar por fase (puente al motor de video).",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "fase": {"type": "string", "description": "HOOK | DOLOR | SOLUCION | DESEO | CTA"},
                                    "buscar": {"type": "string", "description": "qué toma buscar en TikTok (corto y concreto)"},
                                },
                                "required": ["fase", "buscar"],
                            },
                        },
                    },
                    "required": ["hook", "angulo", "guion", "copy_pantalla"],
                },
            }
        },
        "required": ["variaciones"],
    },
}


def generar_variaciones(arco_texto: str, product_desc: str, anthropic_key: str, *,
                        page_text: str = "", n: int = 6, con_escenas: bool = True) -> list[dict]:
    """De un creativo GANADOR (su arco/guion en texto) + el producto → N variaciones de hook/guion/copy
    (+ brief de escenas por fase si `con_escenas`). Devuelve [] si falla (nunca lanza)."""
    if not (anthropic_key and (arco_texto.strip() or product_desc.strip())):
        return []
    ctx = f"PRODUCTO: {product_desc}\n"
    if page_text.strip():
        ctx += f"\nCONTEXTO DE LA PÁGINA:\n{page_text[:2000]}\n"
    ctx += f"\nCREATIVO GANADOR (arco/guion que YA funciona — CONSÉRVALO):\n{arco_texto[:4000]}\n"
    ctx += (f"\nSaca EXACTAMENTE {n} variaciones MUY distintas. "
            + ("Incluye el brief de ESCENAS por fase (modo hook + tomas)."
               if con_escenas else "NO incluyas escenas (solo varío el hook/guion/copy)."))
    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=anthropic_key)
        resp = client.messages.create(
            model=_CLAUDE, max_tokens=14000, system=_SISTEMA,
            tools=[_TOOL], tool_choice={"type": "tool", "name": "entregar_variaciones"},
            messages=[{"role": "user", "content": ctx}],
        )
        for block in resp.content:
            if getattr(block, "type", None) == "tool_use" and block.name == "entregar_variaciones":
                return list(block.input.get("variaciones", []))
    except Exception as e:  # noqa: BLE001
        print(f"⚠️  Variaciones (Claude) no disponibles: {e}")
    return []
