(async () => {
  const token = JSON.parse(localStorage['DROPI_LoginResult']).token;
  const kws = ["accesorios para carro", "limpieza carro", "alfombra", "decoracion hogar", "organizador cocina", "utensilios cocina", "limpieza hogar", "quitamanchas", "cuidado de la piel", "crecimiento cabello", "dolor de espalda", "corrector postura", "ejercicio en casa", "faja reductora", "accesorios perros", "juguete gato", "accesorios bebe", "juguete didactico", "audifonos inalambricos", "smartwatch", "zapatos ortopedicos", "reloj hombre", "pago contra entrega", "paga al recibir"];
  const porId = {};
  for (const kw of kws) {
    try {
      const r = await fetch('https://api.dropi.co/api/products/v4/index', {
        method: 'POST',
        headers: {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token},
        body: JSON.stringify({pageSize: 85, startData: 0, privated_product: false,
          userVerified: false, favorite: false, with_collection: true, get_stock: true,
          no_count: true, search_type: 'simple', country: 'COLOMBIA', keywords: kw})
      });
      const j = await r.json();
      for (const o of (j.objects || [])) {
        const stock = (o.warehouse_product || []).reduce((s, w) => s + (w.stock || 0), 0);
        porId[o.id] = {dropi_id: String(o.id), nombre: o.name, stock: stock,
          sale_price: o.sale_price, suggested_price: o.suggested_price};
      }
      console.log('[stock_masivo]', kw, '→', (j.objects || []).length);
    } catch (e) { console.log('[stock_masivo] ERROR', kw, String(e)); }
    await new Promise(res => setTimeout(res, 400));
  }
  const out = Object.values(porId);
  window.__stock_masivo = JSON.stringify(out);
  console.log('[stock_masivo] TOTAL:', out.length, 'productos únicos — JSON en window.__stock_masivo');
  try { copy(window.__stock_masivo); console.log('[stock_masivo] copiado al portapapeles'); } catch (e) {}
  return out.length;
})()