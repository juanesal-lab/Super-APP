# 💾 RESTORE — Recuperar tus claves y estado desde el respaldo

La app respalda sola (cada vez que la prendes, y con el botón **“Respaldar ahora”** en 🔑 Claves)
lo IRREEMPLAZABLE que NO está en git:

- `.env` — tus 7+ API keys de la app (Gemini, ElevenLabs, Claude, Foreplay, Pexels/Pixabay, ScrapeCreators, Shopify)
- `montador/.env` — keys de la app Montador
- `radar/.env`, `radar/radar.db`, `radar/config.json`, `radar/privado.json` — estado del 📡 Radar

Se guardan en **`~/Backups/creativemaxing/<YYYY-MM-DD>/`** (FUERA del repo git), con la MISMA
estructura del repo, y se conservan los **últimos 14 días**. Las carpetas van con permisos `700`
y los archivos `600` porque contienen secretos.

---

## 1) Ver qué respaldos tienes

```bash
ls -lt ~/Backups/creativemaxing/
```

La carpeta de arriba (fecha más nueva) es la más reciente. Mira qué contiene:

```bash
ls -laR ~/Backups/creativemaxing/2026-07-15/    # usa TU fecha
```

## 2) Restaurar TODO (recuperación total)

Desde la raíz del repo (`Super-APP/`), copia de vuelta el respaldo más reciente. `-n` NO
sobrescribe lo que ya exista (seguro); quita el `-n` si quieres forzar el reemplazo.

```bash
cd ~/Transcriptor/Super-APP                      # la raíz de tu repo
DIA=$(ls ~/Backups/creativemaxing/ | sort | tail -1)   # el día más reciente
cp -Rn ~/Backups/creativemaxing/"$DIA"/. .        # copia respetando la estructura
```

## 3) Restaurar SOLO un archivo (lo más común: perdiste el .env)

```bash
cd ~/Transcriptor/Super-APP
DIA=$(ls ~/Backups/creativemaxing/ | sort | tail -1)
cp ~/Backups/creativemaxing/"$DIA"/.env  .env             # las API keys de la app
cp ~/Backups/creativemaxing/"$DIA"/montador/.env  montador/.env
cp ~/Backups/creativemaxing/"$DIA"/radar/radar.db  radar/radar.db   # base del Radar
```

## 4) Comprobar y arrancar

```bash
head -1 .env            # ¿está tu GEMINI_API_KEY=...?
./run.sh                # prende la app; en 🔑 Claves las pills deben decir "configurada ✓"
```

---

### Notas
- Si quieres restaurar de un día ANTERIOR (no el más nuevo), pon la fecha a mano en vez de `$DIA`.
- El respaldo NO incluye `work/`, `uploads/`, `venv/` ni `models/`: son pesados y se regeneran solos.
- Forzar un respaldo manual sin abrir la web:
  `./venv/bin/python -c "import sys; sys.path.insert(0,'backend'); from pipeline.backups import respaldar; print(respaldar())"`
