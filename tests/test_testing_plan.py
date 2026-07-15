"""Pruebas OFFLINE ($0) del Plan de testeo 2026 (backend/pipeline/testing_plan.py)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from pipeline.testing_plan import generar_plan_testeo, _slug, _ad_name, UMBRALES  # noqa: E402


def _versions():
    return [
        {"name": "A_gancho", "stage": "TOFU", "avatar": "Deportista lesionado", "hook_text": "PARA DE SUFRIR"},
        {"name": "B_narrativa", "stage": "MOFU", "avatar": "Abuela con artrosis"},
        {"name": "C_corta", "stage": "BOFU", "avatar": "Oficinista sedentario"},
    ]


def test_slug_sin_acentos_mayus():
    assert _slug("Señora de 60 años") == "SENORA-DE-60-ANOS"
    assert _slug("") == ""


def test_ad_name_incluye_avatar_y_etapa():
    v = {"name": "A_gancho", "stage": "TOFU", "avatar": "Deportista lesionado"}
    nm = _ad_name("Rodillera Magnética", v, 0)
    assert nm.startswith("RODILLERA")
    assert "TOFU" in nm and "DEPORTISTA" in nm and nm.endswith("v1")


def test_plan_estructura_completa():
    plan = generar_plan_testeo(_versions(), producto="Rodillera")
    assert plan["ok"] and plan["n_versiones"] == 3
    for k in ("estructura_campana", "senales", "decision", "iteracion", "refresh", "filas", "markdown"):
        assert k in plan, f"falta {k}"
    # umbrales duros del research presentes en el texto
    md = plan["markdown"]
    assert "Escalar" in md and "Matar" in md and "Iterar" in md
    assert "25" in md and "30" in md  # hook rate itera/escala
    # una fila por versión con su nombre de anuncio
    assert len(plan["filas"]) == 3
    assert all(f["ad_name"] for f in plan["filas"])


def test_sin_cpa_da_regla_no_cifra_inventada():
    """Sin CPA ni precio: NO inventa montos (regla de oro), da los múltiplos."""
    plan = generar_plan_testeo(_versions(), producto="X")
    assert any("no cifras" in a.lower() or "REGLAS" in a for a in plan["avisos"])
    assert "1.5–2×" in plan["decision"]["muestra_minima"]


def test_con_cpa_calcula_montos():
    plan = generar_plan_testeo(_versions(), producto="X", cpa_objetivo=25000, moneda="COP")
    # 1.5-2x de 25000 = 37.500-50.000
    assert "37.500" in plan["decision"]["muestra_minima"]
    assert "50.000" in plan["decision"]["muestra_minima"]
    assert "COP" in plan["decision"]["muestra_minima"]


def test_lote_chico_avisa():
    plan = generar_plan_testeo(_versions()[:1], producto="X")
    assert any("mínimo sano" in a for a in plan["avisos"])


def test_sin_etapa_avisa_embudo():
    vs = [{"name": "A_gancho", "avatar": "X"}]
    plan = generar_plan_testeo(vs, producto="P")
    assert any("etapa" in a.lower() for a in plan["avisos"])


def test_entrada_vacia_no_rompe():
    plan = generar_plan_testeo([], producto="")
    assert plan["ok"] and plan["n_versiones"] == 0
    assert isinstance(plan["markdown"], str)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n✅ {len(fns)}/{len(fns)} OK")
