# 📮 Feedback de Jack desde la app (para que la terminal/Claude mejore el CÓDIGO)

Cada entrada = una prueba que no gustó + qué mejorar. La IA lo lee al arrancar una sesión y ajusta el código (blur, sincronía, etc.). Al resolver, marca la entrada como ✅ hecho.

## ✅ hecho — 2026-07-08 08:36 · job 96e6fd354da0 (entrada duplicada, era la misma prueba)
- **Problemas marcados:** El blur, Los clips no cuadran con la voz
- **Jack dice:** los mas imortante se estan repitiendo siempre los mismos clips bro mejora esa puta mierda bro el hook de los primeros 4 segundo no esta varia mas los clips y esta pasando lo mismpo del blur , bro el 2x1 lo dice muy raro en eleven labs no pongas 2x1 sino 2 por 1  y falta el riser
- **Video:** /api/file?path=%2FUsers%2Fjaca%2FTranscriptor%2FSuper-APP%2Fwork%2F96e6fd354da0%2Fversion_A_gancho_vo_of.mp4
- **Resuelto (todo commiteado el mismo 07-08, ver DEV-LOG):** repetición de clips → fix definitivo (montaje por DURACIÓN + dedup multi-firma); blur → esmerilado ilegible en vez de bloque sólido + selector suave/medio/fuerte + priorizar clips SIN texto; "2x1" → `_dub_2x1_line` lo dicta "2 por 1" (protegido en tests/smoke.py); riser → 12 SFX generados (riser, whoosh, boom...) con HOOK→riser en phase_effects/pro_mix.
