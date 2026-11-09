# 🛰️ Radar de Ofertas

Bot de afiliación **100% automatizado y sin coste**: vigila ofertas de Amazon,
las valida con un **analista cuantitativo (GLM)**, publica las ofertas
aprobados en **tu canal de Telegram** con **tu enlace de afiliado** y los
**reparte solo a más superficies** (web SEO, Bluesky, Discord, Reddit, canales
extra) para captar compradores fuera del canal.

- ✅ Sin inventario, sin inversión inicial, sin cuentas de pago
- ✅ Descuento mínimo real configurable (por defecto **≥ 20%**)
- ✅ Valoración mínima **≥ 4.0★** con **≥ 50 reseñas** (verificada contra la página real de Amazon)
- ✅ Rechazo de réplicas, marcas prohibidas y señales de fraude
- ✅ Redacción del mensaje estilo "oferta" en español neutro (LatAm/USA)
- ✅ **Captación automática**: cada oferta se convierte en ficha SEO + posts en redes
- ✅ Corre en la nube gratis con **GitHub Actions** cada 2 horas

---

## Arquitectura

```
 ┌─────────────────────── RECOLECTAR ───────────────────────┐
 │  Feeds RSS de ofertas (9to5toys/9to5mac/9to5google)      │
 │  Búsqueda Amazon (opcional, IP residencial)              │
 └──────────────────────┬───────────────────────────────────┘
                        ▼
 ┌──────────────── FILTRO DURO (código, gratis) ────────────┐
 │  ¿precio? ¿descuento ≥ 20%? ¿rating ≥ 4.0?               │
 │  ¿palabras/marcas prohibidas? ¿título spam?              │
 └──────────────────────┬───────────────────────────────────┘
                        ▼
 ┌────────────── ENRIQUECER (página de producto Amazon) ────┐
 │  Precio real · precio de lista · ★ rating · nº reseñas   │
 └──────────────────────┬───────────────────────────────────┘
                        ▼
 ┌──────────── ANALISTA CUANTITATIVO (GLM, API Z.ai) ───────┐
 │  ¿El descuento es REAL? ¿ancla de precio inflada?        │
 │  ¿fraude? ¿marca legítima? → VEREDICTO JSON + MENSAJE    │
 └──────────────────────┬───────────────────────────────────┘
                        ▼
 ┌──────────── PUBLICAR EN TELEGRAM (Bot API) ──────────────┐
 │  Mensaje de oferta + enlace ?tag=TU-TAG + disclosure        │
 └──────────────────────┬───────────────────────────────────┘
                        ▼
 ┌──── CAPTACIÓN AUTOMÁTICA (prospección multi-superficie) ─┐
 │  Sitio SEO en Pages · Bluesky · Discord webhooks         │
 │  Reddit (opcional) · canales/grupos extra de Telegram    │
 │  Cada oferta = 1 ficha indexable con JSON-LD + RSS       │
 └──────────────────────┬───────────────────────────────────┘
                        ▼
 ┌──── DEDUPLICACIÓN (SQLite persistida en el repo) ────────┐
 │  Tabla seen (nunca repite) + snapshot deals (sitio)      │
 └──────────────────────────────────────────────────────────┘
```

**Resultados de las pruebas reales** (nov 2026): los feeds 9to5 responden 200,
la página de producto de Amazon es accesible desde la nube (con *throttling*,
el sistema degrada con elegancia), la búsqueda de Amazon bloquea IPs de
datacenter (queda desactivada por defecto) y el prompt GLM devuelve el JSON de
veredicto exacto validado.

---

## Estructura del proyecto

```
radar-de-ofertas/
├── .github/workflows/radar.yml   # Automatización en GitHub Actions (cada 2 h)
├── radar/
│   ├── main.py                   # Orquestador CLI (--demo / --dry-run / --collect-only)
│   ├── config.py                 # Carga config.yaml + variables de entorno
│   ├── models.py                 # Dataclass Deal: la oferta que viaja por el pipeline
│   ├── utils.py                  # HTTP con reintentos, parseo de precios, ASIN, logging
│   ├── demo.py                   # 7 casos de prueba + veredictos simulados
│   ├── collectors/
│   │   ├── rss_feeds.py          # Fuente 1: feeds RSS → artículo → ASIN de Amazon
│   │   ├── amazon_search.py      # Fuente 2: búsqueda Amazon (opcional)
│   │   └── amazon_product.py     # Enriquecedor: precio/rating/reseñas reales
│   ├── analysis/
│   │   ├── rules.py              # Filtro duro pre-IA (ahorra tokens)
│   │   ├── prompt.py             # ⭐ EL PROMPT EXACTO del analista (edítalo aquí)
│   │   └── glm_client.py         # Cliente API Z.ai + reintentos + fail-closed
│   ├── publish/
│   │   ├── affiliate.py          # Construye el enlace con tu tag de afiliado
│   │   ├── compose.py            # Mensaje TG + variantes Bluesky/Discord/Reddit
│   │   ├── telegram.py           # Bot API (gestiona 429 y fallos de parseo)
│   │   ├── fanout.py             # ⭐ Prospección: reparte la oferta a todas las superficies
│   │   ├── web.py                # ⭐ Sitio SEO estático (fichas JSON-LD, RSS, sitemap)
│   │   ├── bluesky.py            # Post automático (AT Protocol, gratis)
│   │   ├── discord.py            # Webhooks de servidores de ofertas
│   │   └── reddit.py             # Opcional, desactivado (respeta reglas de cada sub)
│   └── storage/store.py          # SQLite: deduplicación + snapshot de ofertas publicadas
├── config.yaml                   # ⭐ Umbrales, fuentes, marcas prohibidas...
├── requirements.txt              # Librerías a instalar
├── .env.example                  # Plantilla de secretos para local
└── README.md
```

---

## Librerías a instalar

```bash
pip install -r requirements.txt
```

| Librería | Para qué |
|---|---|
| `requests` | HTTP para RSS, Amazon, API de GLM y API de Telegram |
| `feedparser` | Parseo robusto de feeds RSS/Atom |
| `beautifulsoup4` | Parseo HTML de páginas de Amazon |
| `PyYAML` | Leer `config.yaml` |
| `python-dotenv` | Cargar secretos desde `.env` en local |

Requiere **Python 3.10+** (probado con 3.12).

---

## Puesta en marcha desde cero

### Paso 0 · Prueba el motor sin configurar nada (30 segundos)

```bash
pip install -r requirements.txt
python -m radar.main --demo --dry-run
```

Verás el pipeline completo: 3 ofertas aprobadas con su mensaje, 4 descartados
(descuento insuficiente, réplica, rating bajo, fraude). **No necesita claves ni internet.**

### Paso 1 · Bot de Telegram (5 min)

1. Habla con **@BotFather** → `/newbot` → elige nombre y usuario → **guarda el token** (`123456:ABC-...`).
2. Crea tu canal (público, p. ej. `@OfertasDelRadar`) y añade el bot como **administrador** con permiso de *publicar mensajes*.
3. Si el canal es **privado**, consigue su ID numérico (formato `-100...`) añadiendo el bot, publicando algo y abriendo `https://api.telegram.org/bot<TOKEN>/getUpdates`.

### Paso 2 · Amazon Afiliados (10 min + espera de aprobación)

1. Regístrate en **associates.amazon.com** (para amazon.com, mercado USA/LatAm).
2. Obtén tu **Tracking ID** (termina en `-20` para amazon.com).
3. Cumplimiento básico que este bot ya respeta:
   - El pie de cada mensaje declara *"Somos afiliados de Amazon"*.
   - Cada precio se publica con sello de tiempo (*"Precio verificado dd/mm hh:mm UTC"*), porque Associates no permite presentar precios como permanentes.
   - Necesitas **3 ventas en 180 días** para que la cuenta no se cierre.
4. ⚠️ Declara en tu canal (en la descripción) que contiene enlaces de afiliado.

### Paso 3 · API key de Z.ai para GLM (3 min)

1. Entra en **z.ai** → consola de API → crea una **API Key**.
2. (Opcional) Cambia el modelo en `config.yaml`: `glm-5.3` (recomendado), `glm-5.2` o `glm-5.1` (más económicos).

### Paso 4 · Prueba local con datos reales (sin publicar)

```bash
cp .env.example .env      # rellena ZAI_API_KEY; el resto puede esperar
python -m radar.main --collect-only    # ¿qué detectan las fuentes HOY?
python -m radar.main --dry-run        # pipeline real, muestra mensajes SIN publicar
```

Cuando estés satisfecho con lo que publica, rellena el `.env` completo.

### Paso 5 · Sube el proyecto a GitHub (10 min)

1. Crea un repositorio **privado** (recomendado) en GitHub.
2. Sube el contenido de esta carpeta (excepto `.env` — está en `.gitignore`):

```bash
git init
git add .
git commit -m "Radar de Ofertas v1.0"
git branch -M main
git remote add origin https://github.com/TU-USUARIO/radar-de-ofertas.git
git push -u origin main
```

### Paso 6 · Configura los Secrets (2 min)

En el repo: **Settings → Secrets and variables → Actions → New repository secret**

| Secret | Valor |
|---|---|
| `ZAI_API_KEY` | Tu API key de Z.ai |
| `TELEGRAM_BOT_TOKEN` | Token de @BotFather |
| `TELEGRAM_CHAT_ID` | `@tu_canal` o `-100xxxxxxxxxx` |
| `AMAZON_TAG` | Tu Tracking ID (p. ej. `miradar-20`) |

### Paso 7 · Arranca la automatización (1 min)

1. Pestaña **Actions** del repo → habilita workflows si te lo pide.
2. Selecciona **"Radar de Ofertas" → Run workflow** para la primera ejecución manual.
3. Revisa los logs: verás la recolección, los filtros, los veredictos GLM y las publicaciones.
4. A partir de aquí corre **solo, cada 2 horas** (cron `37 */2 * * *` en UTC).

### Paso 8 · Afina tu radar (opcional)

Todo vive en `config.yaml`:

- `filtros.descuento_min_pct`: el 20% de tu regla de negocio.
- `filtros.rating_min` / `resenas_min`: calidad mínima exigida.
- `filtros.marcas_prohibidas` / `palabras_prohibidas`: tu lista negra anti-réplica.
- `recolectores.rss_feeds.urls`: añade/quita feeds (descomenta Promodescuentos si ejecutas desde IP residencial).
- `publicacion.max_posts_por_ciclo`: no satures el canal.
- `glm.modelo` / `glm.thinking`: equilibrio coste/calidad del analista.
- `.github/workflows/radar.yml` → línea `cron`: cambia la frecuencia.

El **prompt exacto** del analista vive en `radar/analysis/prompt.py`: ahí puedes
ajustar el tono, el formato del mensaje o endurecer cualquier criterio sin
tocar código.

### Paso 9 · Activa la CAPTACIÓN AUTOMÁTICA (el negocio prospecta solo)  

A partir de aquí cada oferta aprobada se reparte solo a superficies donde ya
hay cazadores de ofertas. Todas son opcionales y gratuitas:

**9a. Sitio SEO en GitHub Pages (tráfico de Google 24/7 — la más rentable)**

Cada oferta se convierte en una ficha indexable (`site/p/…html`) con JSON-LD
Product/Offer, portada, RSS (`site/feed.xml`) y sitemap. Para publicarlo:

1. Repo → **Settings → Pages** → *Build and deployment* → Source: **GitHub Actions**.
2. Nada más: el workflow ya despliega `site/` en cada ciclo (si Pages no está
   activo, el paso se salta sin romper la ejecución).
3. Tu web queda en `https://TU-USUARIO.github.io/radar-de-ofertas/` (el sistema la
   deduce solo; si usas otro dominio, define el secret `SITE_BASE_URL`).
4. (Recomendado) Registra el sitemap en **Google Search Console**: acelera el
   indexado semanas.
5. Añade tu canal en el secret `TELEGRAM_CHANNEL_URL`: cada ficha incluye un
   botón "únete al canal" — el sitio convierte buscadores en suscriptores.

**9b. Bluesky (post automático por oferta)**

1. Crea la cuenta (gratis) → **Ajustes → Contraseñas de app** → crea una.
2. Secrets: `BLUESKY_HANDLE` y `BLUESKY_APP_PASSWORD`.
3. Activa `captacion.bluesky.enabled: true` en `config.yaml`.

**9c. Discord (webhooks a servidores de ofertas)**

1. En cada servidor donde el dueño acepte un canal de ofertas: **Ajustes del
   canal → Integraciones → Webhooks → Nuevo webhook → Copiar URL**.
2. Secret `DISCORD_WEBHOOK_URLS` con una o varias URLs separadas por coma.

**9d. Telegram extendido (réplica a más canales/grupos)**

Secret `TELEGRAM_CHAT_IDS` con canales/grupos donde tu bot sea admin,
separados por coma (`@canal2,-1001234…`). Útil para un segundo canal temático
o grupos que te pidan bot.

**9e. Reddit (OPCIONAL — lée esto antes de tocarlo)**

Desactivado por defecto. La mayoría de subreddits de ofertas **prohíben**
enlaces de afiliado o exigen disclosure explícito; publicar sin leer sus
reglas cuesta la cuenta y el shadowban de tu dominio. Si decides usarlo:
app tipo *script* en reddit.com/prefs/apps, 4 secrets `REDDIT_*`, y activa
`captacion.reddit` con UN subreddit concreto tras leer sus reglas.

⚠️ **Sobre "prospectar por DM"**: la Bot API de Telegram no permite escribirle
primero a un usuario que no inició el chat, y automatizar una cuenta personal
para spam en frío viola los Términos de Servicio (ban garantizado con el
tiempo). Por eso la captación de este sistema va por superficies públicas:
funciona 24/7, es escalable y no arriesga ninguna cuenta.

---

## Ejemplo de mensaje publicado

```
🔥 OFERTÓN: -42%
🎧 Bose QuietComfort Ultra
💰 $249 (antes $429)
⭐ 4.7★ (18,420 reseñas)
Los tope de gama de Bose con cancelación adaptativa y audio espacial: $180 de ahorro real.

👉 COMPRAR EN AMAZON          ← tu enlace ?tag=TU-TAG-20
🏷️ Somos afiliados de Amazon · ⏱ Precio verificado 09/11 08:00 UTC
```

---

## Coste total: $0

| Componente | Coste |
|---|---|
| GitHub Actions (2000 min/mes gratis; el ciclo usa ~3 min) | $0 |
| GitHub Pages (sitio SEO de captación, ancho de banda ilimitado para repos públicos/privados Pro) | $0 |
| Feeds RSS de ofertas | $0 |
| API de Telegram | $0 |
| Bluesky / Discord webhooks | $0 |
| API de GLM | Casi $0 (≈1.000 tokens por candidata; ~150 análisis/día máx. → fracciones de dólar al mes) |

---

## Solución de problemas

| Síntoma | Causa y solución |
|---|---|
| `Feed inaccesible (HTTP 403)` en Promodescuentos | Cloudflare bloquea IPs de nube. Normal; los feeds 9to5 sí funcionan. Ejecuta en local para usarlo. |
| `Búsqueda de Amazon bloqueada` | Esperado desde GitHub Actions. Deja `amazon_busqueda.enabled: false` en la nube. |
| `enriquecimiento_bloqueado:503` en los logs | Amazon aplicó *throttling*. El sistema sigue con los datos del título; en el siguiente ciclo reintentará. |
| `Token de bot inválido` | Token mal copiado. Regenera con @BotFather → /token. |
| `Telegram 403: bot is not a member` | No añadiste el bot como **administrador** del canal. |
| `Telegram 429` | Rate limit: el bot ya espera solo (`pausa_entre_mensajes_seg`). |
| `HTTP 401` en GLM | API key incorrecta o sin saldo. Revísala en la consola de Z.ai. |
| `error_analisis` en flags | GLM no devolvió JSON 2 veces → **fail-closed**: la oferta no se publica (por diseño). |
| `Captación FALLÓ → bluesky:...` en el log | Credenciales mal puestas o contraseña de app revocada. El ciclo sigue; revisa `BLUESKY_HANDLE`/`BLUESKY_APP_PASSWORD`. |
| `Discord webhook 404/403` | El webhook se borró o cambió. Copia la URL de nuevo en `DISCORD_WEBHOOK_URLS`. |
| El paso *Publish on GitHub Pages* se salta con un aviso | Pages aún no está activo (Paso 9a). El resto del ciclo funciona igual. |
| El sitio muestra "Aún no hay ofertas" | Normal en el primer ciclo si todo fue rechazado; se llena solo. |
| Publica poco o nada el primer día | Con filtros estrictos es normal. Baja `descuento_min_pct` a 15 o `resenas_min` a 10 para aflojar. |
| Quiero republicar algo descartado | Los rechazos se purgan solos tras `ttl_rechazados_dias` (14 por defecto). |

---

## Advertencias honestas

1. **ToS de Amazon**: el scraping de búsqueda va contra sus términos (por eso está apagado por defecto). Los feeds RSS son públicos y la verificación de producto usa pausas y User-Agents rotatorios para minimizar impacto. Alternativa 100% limpia a futuro: **Amazon PA-API** (se desbloquea tras tus primeras 3 ventas).
2. **Las ofertas caducan**: el sello de hora en cada mensaje y en cada ficha web protege al lector y a tu cuenta de Associates.
3. **GLM puede equivocarse**: el sistema es *fail-closed* (duda = no publicar) y la capa de reglas duras ya elimina el 40-60% de la basura antes de gastar un token.
4. **Captación = dar valor, no spam**: publica en Discord/Reddit solo en comunidades que acepten ofertas con afiliación, con disclosure claro. Una comunidad que te banea es más cara de recuperar que mil clics.

## Roadmap

- 📸 `sendPhoto` con la imagen del producto (ya se captura `og:image`)
- 📉 Validación de precio con historial (Keepa API) para blindar el "descuento real"
- 🔗 Métricas de clics por superficie (amzn.to + reports de Associates)
- 📊 Digest diario con los 5 mejores ofertas del día
- 🌎 Fuente Promodescuentos activa desde IP residencial (red Pepper, LatAm)
