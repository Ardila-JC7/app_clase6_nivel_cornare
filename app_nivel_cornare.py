"""
App básica de Streamlit — Nivel de ríos/quebradas (CORNARE / MARCO)
--------------------------------------------------------------------
Cada estudiante debe cambiar, como mínimo, el código de la estación
en el sidebar. Los valores de fecha y calidad también son ajustables.

Para correrla:
    streamlit run app_nivel_cornare.py
"""

import requests
import pandas as pd
import numpy as np
import streamlit as st
import altair as alt
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ------------------------------------------------------------------
# Coordenadas por defecto (estación San Rafael - Río Guatapé)
# Se usan solo si la API no trae la latitud/longitud de la estación.
# ------------------------------------------------------------------
LAT_DEFECTO = 6.2942
LON_DEFECTO = -75.06251

API_BASE_URL = "https://marco.cornare.gov.co/api/v1/estaciones"

LLAVE_FECHA = "level_date"
LLAVE_VALOR = "level"
CANDIDATOS_LAT = ["lat", "latitude", "latitud"]
CANDIDATOS_LON = ["lng", "lon", "longitude", "longitud"]

# ------------------------------------------------------------------
# Parámetros de la consulta — YA NO SON EDITABLES POR EL USUARIO.
# Antes eran cajas de texto/fecha en el sidebar; ahora son valores fijos.
# ------------------------------------------------------------------
NOMBRE_ESTUDIANTE = "Julián Ardila Castrillón"
CODIGO_ESTACION = "49"
FECHA_DESDE = "2026-06-26"
FECHA_HASTA = "2026-07-02"
CALIDAD = 1  # 1 = solo datos validados, 0 = todos

# Umbrales de alerta para la gráfica de nivel (estación San Rafael - código 49)
NIVEL_ALERTA_AMARILLA = 344
NIVEL_ALERTA_NARANJA = 367
NIVEL_ALERTA_ROJA = 429

# ---------------------------------------------------------------
# Perfil del cauce (ancho vs. elevación del lecho, en cm)
# ---------------------------------------------------------------
PERFIL_CAUCE = pd.DataFrame(
    {
        "distancia": [0, 3, 6, 9, 12, 15, 18, 21, 24, 27, 30, 33, 36, 39, 42, 45, 48, 51, 54, 57, 60, 63, 65, 67, 70],
        "profundidad": [90, 55, 40, 45, 35, 30, 40, 50, 55, 70, 90, 70, 55, 45, 35, 20, 5, 15, 45, 60, 90, 180, 320, 500, 650],
    }
)

st.set_page_config(page_title="Nivel de estación — CORNARE", page_icon="🌊", layout="wide")


# ------------------------------------------------------------------
# Funciones de consulta
# ------------------------------------------------------------------
def obtener_serie_nivel(codigo_estacion, desde, hasta, calidad=1, timeout=30):
    url = f"{API_BASE_URL}/{codigo_estacion}/nivel"
    params = {"desde": desde, "hasta": hasta, "calidad": calidad}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
    }
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=timeout, verify=False)
        if resp.status_code == 200:
            return resp.json(), None
        return None, f"HTTP {resp.status_code}"
    except requests.exceptions.RequestException as e:
        return None, f"Error de red: {e}"


def obtener_todas_las_paginas(datos_json, timeout=30):
    registros = list(datos_json.get("values", []))
    siguiente_url = datos_json.get("next")
    while siguiente_url:
        try:
            resp = requests.get(siguiente_url, timeout=timeout, verify=False)
        except requests.exceptions.RequestException:
            break
        if resp.status_code != 200:
            break
        pagina = resp.json()
        registros.extend(pagina.get("values", []))
        siguiente_url = pagina.get("next")
    return registros


def detectar_coordenadas(datos_json):
    """Busca lat/lon en las llaves raíz de la respuesta. Si no las encuentra, usa el valor por defecto."""
    if not isinstance(datos_json, dict):
        return LAT_DEFECTO, LON_DEFECTO, False

    lat = next((datos_json[k] for k in CANDIDATOS_LAT if k in datos_json), None)
    lon = next((datos_json[k] for k in CANDIDATOS_LON if k in datos_json), None)

    if lat is not None and lon is not None:
        try:
            return float(lat), float(lon), True
        except (TypeError, ValueError):
            pass
    return LAT_DEFECTO, LON_DEFECTO, False


def calcular_indice_calidad(df):
    """Índice simple (0-100) combinando completitud de la serie y proporción de outliers."""
    if df.empty or len(df) < 2:
        return 0.0, 0, 0

    df_idx = df.set_index("fecha")
    frecuencia_tipica = df["fecha"].diff().dropna().mode()
    if len(frecuencia_tipica) == 0:
        return 0.0, 0, 0
    frecuencia_tipica = frecuencia_tipica[0]

    rango_completo = pd.date_range(start=df_idx.index.min(), end=df_idx.index.max(), freq=frecuencia_tipica)
    esperados = len(rango_completo)
    huecos = esperados - len(df_idx)
    completitud = max(0.0, 1 - (huecos / esperados)) if esperados > 0 else 0.0

    Q1, Q3 = df["nivel"].quantile(0.25), df["nivel"].quantile(0.75)
    IQR = Q3 - Q1
    lim_inf, lim_sup = Q1 - 1.5 * IQR, Q3 + 1.5 * IQR
    es_outlier = (df["nivel"] < lim_inf) | (df["nivel"] > lim_sup) | (df["nivel"] < 0)
    proporcion_outliers = es_outlier.mean()

    indice = (completitud * 0.7 + (1 - proporcion_outliers) * 0.3) * 100
    return round(indice, 1), int(huecos), int(es_outlier.sum())


def mostrar_imagen_segura(ruta, caption):
    """Muestra una imagen si el archivo existe; si no, deja un aviso en su lugar."""
    try:
        st.image(ruta, caption=caption, use_container_width=True)
    except Exception:
        st.info(f"📷 Aquí va la imagen: **{ruta}** (aún no se ha agregado al repositorio).")


def graficar_seccion_cauce(nivel_actual, perfil=PERFIL_CAUCE,
                            umbral_amarilla=NIVEL_ALERTA_AMARILLA,
                            umbral_naranja=NIVEL_ALERTA_NARANJA,
                            umbral_roja=NIVEL_ALERTA_ROJA):
    """Construye la gráfica 'Sección del cauce': perfil del lecho + agua
    hasta el nivel actual, junto con la barra vertical de zonas de alerta."""
    df_perfil = perfil.copy()
    # Techo del área azul: el nivel actual, salvo donde el lecho ya está
    # por encima de ese nivel (ahí no hay agua, queda expuesto el terreno).
    df_perfil["techo_agua"] = df_perfil["profundidad"].where(
        df_perfil["profundidad"] >= nivel_actual, nivel_actual
    )

    base = alt.Chart(df_perfil).encode(x=alt.X("distancia:Q", title="Ancho cauce (m)"))

    lecho = base.mark_area(color="#c2b280").encode(
        y=alt.Y("profundidad:Q", title="Nivel (cm)"), y2=alt.value(0)
    )
    agua = base.mark_area(color="#87ceeb", opacity=0.85).encode(
        y="profundidad:Q", y2="techo_agua:Q"
    )
    linea_nivel = (
        alt.Chart(pd.DataFrame({"nivel": [nivel_actual]}))
        .mark_rule(strokeDash=[6, 3], color="#0b3d91", strokeWidth=2)
        .encode(y="nivel:Q")
    )

    perfil_chart = (lecho + agua + linea_nivel).properties(width=550, height=350)

    # --- Barra vertical de zonas de alerta (verde / amarilla / naranja / roja) ---
    zonas = pd.DataFrame(
        {
            "zona_x": ["Nivel", "Nivel", "Nivel", "Nivel"],
            "y0": [0, umbral_amarilla, umbral_naranja, umbral_roja],
            "y1": [umbral_amarilla, umbral_naranja, umbral_roja, umbral_roja + 100],
            "color": ["#2ecc71", "#f1c40f", "#e67e22", "#e74c3c"],
        }
    )
    barra = (
        alt.Chart(zonas)
        .mark_bar(size=40)
        .encode(
            x=alt.X("zona_x:N", title=None, axis=None),
            y=alt.Y("y0:Q", title=None, scale=alt.Scale(domain=[0, umbral_roja + 100])),
            y2="y1:Q",
            color=alt.Color("color:N", scale=None),
        )
    )
    marcador = (
        alt.Chart(pd.DataFrame({"nivel": [nivel_actual], "zona_x": ["Nivel"]}))
        .mark_point(shape="triangle-left", size=250, color="black")
        .encode(x="zona_x:N", y="nivel:Q")
    )
    barra_chart = (barra + marcador).properties(width=80, height=350)

    return alt.hconcat(perfil_chart, barra_chart)


# ------------------------------------------------------------------
# Sidebar — parámetros de la consulta (fijos, ya no editables)
# ------------------------------------------------------------------
st.sidebar.header("🔍 Parámetros de tu consulta")
st.sidebar.text_input("Nombre del estudiante", NOMBRE_ESTUDIANTE, disabled=True)
st.sidebar.text_input("Código de estación", CODIGO_ESTACION, disabled=True)
st.sidebar.date_input("Desde", pd.to_datetime(FECHA_DESDE), disabled=True)
st.sidebar.date_input("Hasta", pd.to_datetime(FECHA_HASTA), disabled=True)
st.sidebar.selectbox(
    "Calidad",
    ["Solo datos validados" if CALIDAD == 1 else "Todos los datos"],
    disabled=True,
)

st.title("🌊 Nivel de ríos y quebradas (San Rafael, Rio Guatapé, Vereda El Bizcocho) — CORNARE")

# ------------------------------------------------------------------
# Consulta y procesamiento
# ------------------------------------------------------------------
with st.spinner("Consultando la API..."):
    datos_crudos, error = obtener_serie_nivel(CODIGO_ESTACION, FECHA_DESDE, FECHA_HASTA, CALIDAD)

if error:
    st.error(f"❌ {error}")
else:
    registros = obtener_todas_las_paginas(datos_crudos)

    if not registros:
        st.warning("No hay registros para esta estación y rango de fechas.")
    else:
        df = pd.DataFrame(registros)
        df = df.rename(columns={LLAVE_FECHA: "fecha", LLAVE_VALOR: "nivel"})
        df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce")
        df["nivel"] = pd.to_numeric(df["nivel"], errors="coerce")
        df = df.dropna(subset=["fecha", "nivel"]).sort_values("fecha").reset_index(drop=True)

        lat, lon, coords_reales = detectar_coordenadas(datos_crudos)
        indice_calidad, huecos, n_outliers = calcular_indice_calidad(df)

        # --- Métricas principales ---
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Lecturas", len(df))
        col2.metric("Nivel promedio", f"{df['nivel'].mean():.2f}")
        col3.metric("Índice de calidad", f"{indice_calidad} / 100")
        col4.metric("Outliers detectados", n_outliers)

        # --- Gráfico: Nivel corriente de agua (con umbrales de alerta) ---
        st.subheader("📊 Nivel corriente de agua")

        linea_nivel = (
            alt.Chart(df)
            .mark_line(color="#1f77b4")
            .encode(x=alt.X("fecha:T", title="Fecha"), y=alt.Y("nivel:Q", title="Nivel"))
        )

        umbrales = pd.DataFrame(
            {
                "nivel": [NIVEL_ALERTA_AMARILLA, NIVEL_ALERTA_NARANJA, NIVEL_ALERTA_ROJA],
                "alerta": ["Alerta amarilla", "Alerta naranja", "Alerta roja"],
                "color": ["#f1c40f", "#e67e22", "#e74c3c"],
            }
        )
        lineas_umbral = (
            alt.Chart(umbrales)
            .mark_rule(strokeDash=[6, 3], strokeWidth=2)
            .encode(y="nivel:Q", color=alt.Color("color:N", scale=None), tooltip=["alerta", "nivel"])
        )

        st.altair_chart((linea_nivel + lineas_umbral).interactive(), use_container_width=True)
        st.caption(
            f"🟡 Alerta amarilla: {NIVEL_ALERTA_AMARILLA} · "
            f"🟠 Alerta naranja: {NIVEL_ALERTA_NARANJA} · "
            f"🔴 Alerta roja: {NIVEL_ALERTA_ROJA}"
        )

        # --- Gráfico: Sección del cauce ---
        st.subheader("📐 Sección del cauce")
        nivel_actual = df["nivel"].iloc[-1]
        st.altair_chart(graficar_seccion_cauce(nivel_actual), use_container_width=False)
        st.caption(
            f"Nivel actual: {nivel_actual:.1f} cm · Último registro: {df['fecha'].iloc[-1].strftime('%d/%m/%Y %H:%M')} · "
            "El perfil del cauce (área café) es ilustrativo — reemplázalo por los datos reales si los consigues."
        )

        # --- Mapa de la estación ---
        st.subheader("🗺️ Ubicación de la estación")
        if not coords_reales:
            st.caption("La API no trajo latitud/longitud de la estación — se muestra el punto de partida por defecto de esta estación (San Rafael). Ajusta `CANDIDATOS_LAT` / `CANDIDATOS_LON` si conoces el nombre real de esas llaves.")
        st.map(pd.DataFrame({"lat": [lat], "lon": [lon]}), zoom=10)

        # --- Imágenes de la estación ---
        st.subheader("📸 Imágenes de la estación")
        st.caption("Reemplaza las rutas de abajo por tus propios archivos (por ejemplo, guárdalos en una carpeta `imagenes/` dentro del repositorio).")
        col_img1, col_img2, col_img3 = st.columns(3)
        with col_img1:
            mostrar_imagen_segura("imagenes/estacion_1.jpg", "Estación de nivel — Vista 1")
        with col_img2:
            mostrar_imagen_segura("imagenes/estacion_2.jpg", "Estación de nivel — Vista 2")
        with col_img3:
            mostrar_imagen_segura("imagenes/estacion_3.jpg", "Estación de nivel — Vista 3")

        # --- Detalle de calidad ---
        with st.expander("Detalle del índice de calidad"):
            st.write(f"- Huecos de reporte detectados: **{huecos}**")
            st.write(f"- Outliers (IQR + nivel negativo): **{n_outliers}** de {len(df)} lecturas")
            st.write("El índice combina completitud de la serie (70%) y proporción de datos sin outliers (30%).")

        # --- Tabla y descarga ---
        with st.expander("Ver datos crudos"):
            st.dataframe(df, use_container_width=True)

        csv = df.to_csv(index=False).encode("utf-8")
        st.download_button("⬇️ Descargar CSV", csv, file_name=f"nivel_estacion_{CODIGO_ESTACION}.csv", mime="text/csv")
