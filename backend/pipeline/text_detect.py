"""Detección PRECISA de texto fotograma por fotograma con EAST (OpenCV DNN).

Mucho más preciso que cajas de Gemini: detecta el texto justo donde está, en cada
frame, y lo tapa con desenfoque solo en esas cajas (sigue el caption sin tapar de más).
"""
from __future__ import annotations

import os
import tempfile
import threading
import urllib.request

import cv2
import numpy as np

from .ffmpeg_utils import run

# Los objetos de OpenCV compartidos (_net EAST, _face Haar) NO son thread-safe.
# El masking corre en paralelo (varios cortes a la vez), así que serializamos las
# llamadas nativas no-seguras con este lock (si no, dos threads a la vez -> SIGSEGV).
_CV_LOCK = threading.Lock()

_MODEL_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "models", "east.pb")
_MODEL_URL = ("https://raw.githubusercontent.com/oyyd/"
              "frozen_east_text_detection.pb/master/frozen_east_text_detection.pb")
_LAYERS = ["feature_fusion/Conv_7/Sigmoid", "feature_fusion/concat_3"]

_net = None
_face = None
DETECT_EVERY = 8      # detecta cada N frames (el tracking temporal rellena entre medio: el texto quemado es estático)
_INW, _INH = 512, 960  # entrada de la red (múltiplos de 32, ratio vertical). A 320x640 EAST perdía líneas enteras (1080p ⇒ texto de ~15px en la red)
_CONF = 0.6           # confianza mínima (EAST está igual de "seguro" en árboles que en texto: no discrimina)
_MIN_H = 0.022        # alto mínimo del texto (fracción): descarta texto chico (envase/ruido)
# Discriminador principal: el texto quemado es una LÍNEA horizontal (más ancha que alta).
# El follaje/arrugas/bordes que confunden a EAST son cuadrados o verticales. Es robusto al
# movimiento de cámara (a diferencia de la persistencia temporal).
_MIN_WH = 1.5         # ancho/alto mínimo para considerar una caja: descarta cuadradas/verticales (árboles, arrugas)
_TEXT_WH = 3.0        # muy horizontal -> línea de texto clara: se conserva aunque no persista (cámara en mano)
_MIN_DETECTIONS = 2   # cajas dudosas (poco anchas): exige persistir en >=2 frames de detección (mata parpadeos)
_IOU = 0.3            # dos cajas son "la misma" (misma posición) si su IoU >= esto
_BLOCK_GAP = 0.6      # une líneas del mismo BLOQUE si el hueco vertical < esto × alto de línea (tapa el párrafo entero)
_BLOCK_XOVER = 0.3    # ...y se solapan horizontalmente al menos esta fracción de la línea más angosta
_TRACK_GAP = 24       # tracking: una caja re-detectada hasta N frames después sigue siendo el MISMO texto (rellena huecos)
_PAD_FRAMES = 6       # colchón: extiende el tapado N frames antes/después del tramo detectado (sin parpadeo en bordes)
_BOX_PAD_W = 0.05     # margen de seguridad horizontal del bloque final (fracción del ancho)
_BOX_PAD_H = 0.12     # margen de seguridad vertical del bloque final (fracción del alto)


def ensure_model() -> bool:
    """Descarga el modelo EAST (~92 MB) la primera vez si aún no existe.

    Devuelve True si el modelo está disponible (ya estaba o se descargó bien).
    Si falla la descarga (p. ej. sin internet) devuelve False sin romper la app.
    """
    if os.path.exists(_MODEL_PATH):
        return True
    os.makedirs(os.path.dirname(_MODEL_PATH), exist_ok=True)
    print("⬇️  Descargando modelo de detección de texto (EAST, ~92 MB, solo la primera vez)...")
    tmp_fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(_MODEL_PATH), suffix=".part")
    os.close(tmp_fd)
    try:
        urllib.request.urlretrieve(_MODEL_URL, tmp_path)
        os.replace(tmp_path, _MODEL_PATH)  # renombra solo si bajó completo
        print("✅ Modelo EAST listo.")
        return True
    except Exception as e:
        print(f"⚠️  No se pudo descargar el modelo EAST: {e}")
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        return False


def available() -> bool:
    return os.path.exists(_MODEL_PATH)


def _load():
    global _net
    if _net is None:
        with _CV_LOCK:                       # evita doble-init desde varios threads
            if _net is None:
                _net = cv2.dnn.readNet(_MODEL_PATH)
    return _net


def _faces(frame):
    """Detecta caras (para NO taparlas aunque EAST se confunda)."""
    global _face
    if _face is None:
        with _CV_LOCK:
            if _face is None:
                _face = cv2.CascadeClassifier(
                    cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    try:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        with _CV_LOCK:                       # CascadeClassifier NO es thread-safe -> serializar
            return _face.detectMultiScale(gray, 1.1, 5, minSize=(60, 60))
    except Exception:
        return []


def _on_face(box, faces) -> bool:
    bx, by, bw, bh = box
    cx, cy = bx + bw / 2, by + bh / 2
    for (fx, fy, fw, fh) in faces:
        ex, ey = fx - fw * 0.12, fy - fh * 0.18
        ew, eh = fw * 1.24, fh * 1.36
        if ex <= cx <= ex + ew and ey <= cy <= ey + eh:
            return True
    return False


def _detect(net, frame, conf=_CONF, min_wh=_MIN_WH) -> list[tuple]:
    """Devuelve cajas de texto (x,y,w,h) en pixeles del frame, sin caras ni texto chico."""
    H, W = frame.shape[:2]
    rW, rH = W / float(_INW), H / float(_INH)
    blob = cv2.dnn.blobFromImage(frame, 1.0, (_INW, _INH),
                                 (123.68, 116.78, 103.94), swapRB=True, crop=False)
    # setInput + forward tocan el estado del net compartido: deben ir juntos bajo el lock
    # (si otro thread hace setInput entremedio, este forward usaría la entrada equivocada -> crash).
    with _CV_LOCK:
        net.setInput(blob)
        scores, geo = net.forward(_LAYERS)
    nR, nC = scores.shape[2:4]
    rects, confs = [], []
    for y in range(nR):
        sc = scores[0, 0, y]
        x0, x1, x2, x3 = geo[0, 0, y], geo[0, 1, y], geo[0, 2, y], geo[0, 3, y]
        ang = geo[0, 4, y]
        for x in range(nC):
            if sc[x] < conf:
                continue
            ox, oy = x * 4.0, y * 4.0
            a = ang[x]; co, si = np.cos(a), np.sin(a)
            h = x0[x] + x2[x]; w = x1[x] + x3[x]
            ex = int(ox + co * x1[x] + si * x2[x])
            ey = int(oy - si * x1[x] + co * x2[x])
            rects.append((int((ex - w) * rW), int((ey - h) * rH), int(w * rW), int(h * rH)))
            confs.append(float(sc[x]))
    idx = cv2.dnn.NMSBoxes(rects, confs, conf, 0.4)
    cands = [rects[i] for i in (idx.flatten() if len(idx) else [])
             if rects[i][3] >= _MIN_H * H]   # texto muy chico (envase/ruido) -> ignorar
    faces = _faces(frame) if cands else []   # Haar es caro: solo si hay candidatos
    boxes = []
    for (x, y, w, h) in cands:
        if _on_face((x, y, w, h), faces):   # está sobre una cara -> no es caption
            continue
        # padding: un poco horizontal, más vertical (EAST recorta alto)
        px, py = int(w * 0.10) + 4, int(h * 0.35) + 6
        boxes.append((x - px, y - py, w + 2 * px, h + 2 * py))
    # solo cajas horizontales (líneas de texto). Descarta cuadradas/verticales: follaje,
    # arrugas de tela, bordes... que es donde EAST mete falsos positivos.
    return [(x, y, w, h) for (x, y, w, h) in _merge_lines(boxes, W)
            if w > 0 and h > 0 and w >= h * min_wh]


def _merge_lines(boxes: list[tuple], W: int) -> list[tuple]:
    """Une cajas de la misma línea (y similar) en una sola, para tapar limpio."""
    if not boxes:
        return []
    boxes = sorted(boxes, key=lambda b: b[1])
    merged = []
    for b in boxes:
        x, y, w, h = b
        cy = y + h / 2
        placed = False
        for m in merged:
            mx, my, mw, mh = m
            mcy = my + mh / 2
            if abs(cy - mcy) < max(h, mh) * 0.6:   # misma línea
                nx = min(mx, x); ny = min(my, y)
                nx2 = max(mx + mw, x + w); ny2 = max(my + mh, y + h)
                m[0], m[1], m[2], m[3] = nx, ny, nx2 - nx, ny2 - ny
                placed = True
                break
        if not placed:
            merged.append([x, y, w, h])
    return [tuple(m) for m in merged]


def _merge_blocks(boxes: list[tuple]) -> list[tuple]:
    """Une líneas VECINAS del mismo bloque de texto en una sola caja (párrafo entero).

    Dos cajas se unen si están casi pegadas en vertical (hueco < _BLOCK_GAP × alto de
    línea) y se solapan horizontalmente (>= _BLOCK_XOVER de la más angosta). Así un
    caption de 4 líneas se tapa como UN bloque (antes quedaban la 1ª/última legibles).
    Solo une cajas que YA pasaron el gate de forma + persistencia: no crea falsos positivos.
    """
    boxes = [list(b) for b in boxes]
    changed = True
    while changed:
        changed = False
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                ax, ay, aw, ah = boxes[i]
                bx, by, bw, bh = boxes[j]
                gap = max(ay, by) - min(ay + ah, by + bh)      # hueco vertical (<0 = se solapan)
                xover = min(ax + aw, bx + bw) - max(ax, bx)     # solape horizontal en px
                if gap < _BLOCK_GAP * min(ah, bh) and xover >= _BLOCK_XOVER * min(aw, bw):
                    nx, ny = min(ax, bx), min(ay, by)
                    boxes[i] = [nx, ny, max(ax + aw, bx + bw) - nx, max(ay + ah, by + bh) - ny]
                    boxes.pop(j)
                    changed = True
                    break
            if changed:
                break
    return [tuple(b) for b in boxes]


def _track(confirmed: dict[int, list[tuple]], last_frame: int) -> list[dict]:
    """Agrupa las cajas confirmadas entre frames en TRACKS continuos.

    El texto quemado es estático por tramos: si una caja aparece en t1 y t3 pero no en t2
    (EAST parpadea), el track vive [t1, t3] y el hueco se RELLENA. Cada track guarda sus
    detecciones (fidx, caja) y su tramo [start, end] con _PAD_FRAMES de colchón a cada lado
    (y hasta la siguiente detección al final). La caja por frame la da _box_at.
    """
    tracks: list[dict] = []           # {dets: [(fidx, box)...], start, end}
    for fidx in sorted(confirmed):
        blocks = _merge_blocks(confirmed[fidx])
        for box in blocks:
            best, best_iou = None, 0.0
            for t in tracks:
                if t["dets"][-1][0] == fidx:      # ya recibió una caja en este frame
                    continue
                if fidx - t["dets"][-1][0] > _TRACK_GAP:
                    continue
                v = _iou(box, t["dets"][-1][1])
                if v >= _IOU and v > best_iou:
                    best, best_iou = t, v
            if best is None:
                tracks.append({"dets": [(fidx, box)]})
            else:
                best["dets"].append((fidx, box))
    for t in tracks:
        t["start"] = max(0, t["dets"][0][0] - _PAD_FRAMES)
        t["end"] = min(last_frame, t["dets"][-1][0] + DETECT_EVERY - 1 + _PAD_FRAMES)
    return tracks


def _box_at(track: dict, i: int) -> tuple:
    """Caja FIJA del track (unión de TODAS sus detecciones) — el tapado NO se mueve por la pantalla.

    Antes interpolaba la caja frame a frame y "seguía" la caption: se veía como un bloque
    DESLIZÁNDOSE por la pantalla (queja de Jack: 'el blur se mueve horrible'). Ahora el tapado es
    un rectángulo ESTACIONARIO que cubre toda la zona donde el texto aparece en ese tramo, así que
    queda quieto (el caption quemado es estático de todos modos → la unión es chica). Se cachea."""
    box = track.get("_fixed")
    if box is None:
        dets = track["dets"]
        x0 = min(d[1][0] for d in dets)
        y0 = min(d[1][1] for d in dets)
        x1 = max(d[1][0] + d[1][2] for d in dets)
        y1 = max(d[1][1] + d[1][3] for d in dets)
        w, h = x1 - x0, y1 - y0
        px, py = int(w * _BOX_PAD_W) + 4, int(h * _BOX_PAD_H) + 4   # margen de seguridad espacial
        box = track["_fixed"] = (x0 - px, y0 - py, w + 2 * px, h + 2 * py)
    return box


def _obscure(roi):
    """Tapa el texto con un RELLENO SÓLIDO (no mosaico pixelado, que se veía feo).

    Rellena la caja con el COLOR DE FONDO de la propia zona = la MEDIANA de sus píxeles: como el
    texto es minoría frente al fondo, la mediana ≈ el fondo → el texto desaparece bajo un bloque
    sólido del mismo color, que se ve limpio y se funde con el entorno. Los bordes se difuminan
    apenas ~2 px para que el rectángulo no tenga un canto duro (queda 'perfecto', sin parche). Como
    la caja del track es continua y el fondo del caption es estable, no parpadea."""
    import numpy as np
    h, w = roi.shape[:2]
    if h < 2 or w < 2:
        return roi
    flat = roi.reshape(-1, roi.shape[2]) if roi.ndim == 3 else roi.reshape(-1, 1)
    med = np.median(flat, axis=0)
    solid = np.empty_like(roi)
    solid[:] = med.astype(roi.dtype)
    # feather de ~2 px SOLO en el borde para fundir el bloque sólido con el entorno (sin canto duro)
    b = max(1, min(4, min(w, h) // 20))
    if b >= 1 and w > 4 * b and h > 4 * b:
        mask = np.zeros((h, w), np.float32)
        mask[b:h - b, b:w - b] = 1.0
        mask = cv2.GaussianBlur(mask, (2 * b + 1, 2 * b + 1), 0)
        if roi.ndim == 3:
            mask = mask[:, :, None]
        return (solid * mask + roi * (1.0 - mask)).astype(roi.dtype)
    return solid


def _iou(a: tuple, b: tuple) -> float:
    """Intersección sobre unión de dos cajas (x,y,w,h). 0 = disjuntas, 1 = idénticas."""
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix0, iy0 = max(ax, bx), max(ay, by)
    ix1, iy1 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    inter = max(0, ix1 - ix0) * max(0, iy1 - iy0)
    if inter <= 0:
        return 0.0
    return inter / float(aw * ah + bw * bh - inter)


def _confirm(detections: list[tuple], min_det: int) -> dict[int, list[tuple]]:
    """Filtra falsos positivos combinando forma (aspecto) y persistencia temporal.

    - Caja MUY horizontal (w/h >= _TEXT_WH): es claramente una línea de texto -> se conserva
      aunque aparezca en un solo frame (así no se pierden captions con cámara en movimiento).
    - Caja poco horizontal (dudosa): solo se conserva si PERSISTE en varios frames en la misma
      posición (IoU >= _IOU en >= `min_det` frames). Un caption real persiste; el ruido parpadea.

    `detections`: lista de (frame_index, [cajas]).  Devuelve {frame_index: [cajas confirmadas]}.
    """
    flat = [(fidx, box) for fidx, boxes in detections for box in boxes]
    confirmed: dict[int, list[tuple]] = {}
    for fidx, box in flat:
        x, y, w, h = box
        if w < h * _TEXT_WH:                 # no es "obviamente texto" -> exige persistencia
            frames_seen = {f2 for f2, b2 in flat if _iou(box, b2) >= _IOU}
            if len(frames_seen) < min_det:
                continue
        confirmed.setdefault(fidx, []).append(box)
    return confirmed


def mask_video(in_path: str, out_path: str,
               min_wh: float | None = None, conf: float | None = None) -> str:
    """Tapa el texto detectado frame por frame y conserva el audio.

    Tres pases para evitar falsos positivos (blur donde NO hay texto) y parpadeos:
      1) DETECTAR: recorre el video guardando solo las CAJAS de cada frame de detección
         (no guarda frames -> memoria mínima aunque sea 4K y aunque corran varios clips a la vez).
      2) CONFIRMAR + TRACKEAR: descarta cajas que no persisten (falsos positivos), une las
         líneas de un mismo bloque, y agrupa por IoU entre frames en tracks CONTINUOS
         (si EAST pierde el texto en un frame intermedio, el hueco se rellena; ver _track).
      3) APLICAR: re-lee el video y tapa cada track de forma continua todo su tramo.
    Si no queda nada confirmado, devuelve el original sin re-codificar.

    `min_wh`/`conf`: overrides opcionales del detector. Suben la precisión (menos falsos
    positivos) o la bajan (tapa más). El supervisor (Claude) los ajusta y re-llama cuando
    revisa el resultado. `None` usa los valores por defecto del módulo.
    """
    if not available():
        return in_path
    mw = _MIN_WH if min_wh is None else min_wh
    cf = _CONF if conf is None else conf
    net = _load()
    cap = cv2.VideoCapture(in_path)
    if not cap.isOpened():
        return in_path
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    # ── Pase 1: detectar (guarda solo cajas, no frames) ──
    detections, i = [], 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if i % DETECT_EVERY == 0:
            try:
                boxes = _detect(net, frame, conf=cf, min_wh=mw)
            except Exception:
                boxes = []
            detections.append((i, boxes))
        i += 1
    cap.release()

    # ── Pase 2: filtrar falsos positivos (forma + persistencia) y armar tracks continuos ──
    n = len(detections)
    min_det = _MIN_DETECTIONS if n >= 3 else 1
    confirmed = _confirm(detections, min_det)
    if not confirmed:                 # no hay texto real que tapar -> original tal cual
        return in_path
    total_frames = i
    tracks = _track(confirmed, total_frames - 1)

    # ── Pase 3: aplicar el tapado, CONTINUO durante todo el tramo de cada track ──
    cap = cv2.VideoCapture(in_path)
    tmp = out_path + ".noaudio.mp4"
    writer = cv2.VideoWriter(tmp, cv2.VideoWriter_fourcc(*"mp4v"), fps, (W, H))
    i = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        for t in tracks:
            if not (t["start"] <= i <= t["end"]):   # el track no está activo en este frame
                continue
            x, y, w, h = _box_at(t, i)
            x0, y0 = max(0, x), max(0, y)
            x1, y1 = min(W, x + w), min(H, y + h)
            if x1 > x0 and y1 > y0:
                # caja continua del track (interpolada, no parpadea) + _obscure -> ilegible de verdad
                frame[y0:y1, x0:x1] = _obscure(frame[y0:y1, x0:x1])
        writer.write(frame)
        i += 1
    writer.release()
    cap.release()

    try:
        run(["ffmpeg", "-y", "-i", tmp, "-i", in_path,
             "-map", "0:v:0", "-map", "1:a:0?", "-c:v", "libx264", "-profile:v", "high",
             "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
             "-movflags", "+faststart", "-c:a", "aac", "-shortest", out_path])
        os.remove(tmp)
    except Exception:
        os.replace(tmp, out_path)
    return out_path
