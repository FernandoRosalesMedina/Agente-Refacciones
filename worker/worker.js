/**
 * Cloudflare Worker: proxy para el chat del Agente de Refacciones Críticas.
 *
 * Recibe { pregunta, datos } desde index.html, arma el prompt con el
 * contexto de refacciones y llama a la API de Claude usando la API key
 * guardada como secreto (nunca expuesta al navegador).
 *
 * Configuración (ver README.md):
 *   1) npm install -g wrangler
 *   2) wrangler login
 *   3) wrangler secret put ANTHROPIC_API_KEY
 *   4) Editar ALLOWED_ORIGIN abajo con tu URL real de GitHub Pages
 *   5) wrangler deploy
 */

const ALLOWED_ORIGIN = "https://TU-USUARIO.github.io"; // <-- edita esto

export default {
  async fetch(request, env) {
    if (request.method === "OPTIONS") {
      return new Response(null, { headers: corsHeaders() });
    }

    if (request.method !== "POST") {
      return new Response("Método no permitido", { status: 405, headers: corsHeaders() });
    }

    try {
      const { pregunta, refacciones } = await request.json();

      if (!pregunta) {
        return jsonResponse({ error: "Falta 'pregunta'" }, 400);
      }

      // Limita el contexto para no exceder tokens si el maestro crece mucho
      const contexto = JSON.stringify(refacciones).slice(0, 60000);

      const systemPrompt = `Eres el Agente de Refacciones Críticas de GM Fundición de Aluminio (Toluca).
Respondes preguntas sobre refacciones críticas usando PRIMERO los datos proporcionados abajo.
Toda la lista ya son refacciones críticas (602 en total); no existe un campo adicional de
"criticidad Alta/Media/Baja". Los campos son: codigo_gm, no_parte_fabricante, descripcion,
taller, fabricante_matriz, fabricante_sap, costo_unitario_mxn, lead_time_dias,
stock_matriz_criticidad, min, max, stock_sap (stock real SAP/ZMADE), punto_reorden_sap,
stock_maximo_sap, almacenes_sap, fuente_stock_sap ("OK - cruzado con ZMADE" o "SIN CRUCE - revisar codigo").
Si no encuentras la refacción o el dato en el contexto, dilo claramente, no inventes códigos ni stock.

Tienes acceso a búsqueda web. Úsala SOLO en estos casos:
- La refacción consultada tiene stock_sap en 0, null, o fuente_stock_sap = "SIN CRUCE - revisar codigo".
- El usuario pide explícitamente proveedores, precios, o disponibilidad externa.
En esos casos busca el número de parte fabricante (y descripción si el número es genérico) para
encontrar proveedores, distribuidores o fabricantes, priorizando México cuando sea posible.
Cita de qué sitio sale cada dato que uses de la búsqueda.
No busques en la web para preguntas que ya se responden con los datos del JSON (ej. "¿qué
refacciones son del taller Core Room?").

Responde en español, de forma breve y directa, citando el código GM y/o no. de parte cuando aplique.

DATOS (JSON de refacciones):
${contexto}`;

      const resp = await fetch("https://api.anthropic.com/v1/messages", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "x-api-key": env.ANTHROPIC_API_KEY,
          "anthropic-version": "2023-06-01",
        },
        body: JSON.stringify({
          model: "claude-sonnet-4-6",
          max_tokens: 1500,
          system: systemPrompt,
          messages: [{ role: "user", content: pregunta }],
          tools: [
            {
              type: "web_search_20250305",
              name: "web_search",
              max_uses: 4,
            },
          ],
        }),
      });

      const data = await resp.json();

      if (!resp.ok) {
        return jsonResponse({ error: data.error?.message || "Error de la API" }, resp.status);
      }

      // La respuesta puede traer varios bloques de texto intercalados con
      // bloques de búsqueda web; se concatenan solo los de tipo texto.
      const texto = (data.content || [])
        .map((b) => (b.type === "text" ? b.text : ""))
        .filter(Boolean)
        .join("\n");

      // Fuentes citadas durante la búsqueda web, si las hubo
      const fuentes = (data.content || [])
        .filter((b) => b.type === "text" && b.citations)
        .flatMap((b) => b.citations)
        .map((c) => c.url)
        .filter(Boolean);
      const fuentesUnicas = [...new Set(fuentes)];

      return jsonResponse({
        respuesta: texto,
        fuentes: fuentesUnicas.length ? fuentesUnicas : undefined,
      });
    } catch (err) {
      return jsonResponse({ error: err.message || "Error interno" }, 500);
    }
  },
};

function corsHeaders() {
  return {
    "Access-Control-Allow-Origin": ALLOWED_ORIGIN,
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
  };
}

function jsonResponse(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "Content-Type": "application/json", ...corsHeaders() },
  });
}
