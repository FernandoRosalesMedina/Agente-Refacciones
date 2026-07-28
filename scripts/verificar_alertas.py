#!/usr/bin/env python3
"""
Revisa data/maestro.json y, si hay refacciones críticas con stock SAP en 0,
manda una alerta a un canal de Microsoft Teams vía webhook entrante.
Como toda la lista ya es de refacciones críticas, se alerta sobre cualquier
renglón con stock_sap en 0/None (no hay un nivel adicional de criticidad).

Requiere la variable de entorno TEAMS_WEBHOOK_URL (configurada como secret
en GitHub: Settings → Secrets and variables → Actions → New repository secret).
Si no está configurada, el script no falla, solo avisa y termina.

Cómo crear el webhook en Teams:
  Canal → "..." → Conectores → Webhook entrante → nombrar → Crear → copiar URL.
"""

import os
import sys
import json
import urllib.request


def main():
    webhook = os.environ.get("TEAMS_WEBHOOK_URL")
    if not webhook:
        print("TEAMS_WEBHOOK_URL no configurado, se omite el chequeo de alertas.")
        return

    with open("data/maestro.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    sin_stock = [
        r for r in data.get("refacciones", [])
        if r.get("stock_sap") in (0, None, 0.0)
    ]

    if not sin_stock:
        print("Sin alertas: ninguna refacción crítica en stock 0.")
        return

    lineas = "\n".join(
        f"- **{r.get('codigo_gm')}** — {r.get('descripcion', '')} "
        f"({r.get('taller', 'taller no especificado')})"
        for r in sin_stock[:15]
    )
    extra = f"\n\n...y {len(sin_stock) - 15} más." if len(sin_stock) > 15 else ""

    mensaje = {
        "text": (
            f"⚠️ **Alerta — Refacciones Críticas Fundición**\n\n"
            f"Hay **{len(sin_stock)}** refacción(es) crítica(s) con stock SAP en 0 "
            f"según el último export ZMADE:\n\n{lineas}{extra}"
        )
    }

    req = urllib.request.Request(
        webhook,
        data=json.dumps(mensaje).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req)
        print(f"Alerta enviada: {len(sin_stock)} refacciones críticas sin stock.")
    except Exception as e:
        print(f"No se pudo enviar la alerta a Teams: {e}", file=sys.stderr)
        sys.exit(0)


if __name__ == "__main__":
    main()
