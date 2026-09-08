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
st.caption(f"Estudiante: **{NOMBRE_ESTUDIANTE}** · Estación: **{CODIGO_ESTACION}**")
 
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
 
        # --- Gráfico: Nivel corriente de agua ---
        st.subheader("Nivel corriente de agua")
        st.line_chart(df.set_index("fecha")["nivel"])
 
        # --- Mapa de la estación ---
        st.subheader("Ubicación de la estación")
        if not coords_reales:
            st.caption("La API no trajo latitud/longitud de la estación — se muestra el punto de partida por defecto de esta estación (San Rafael). Ajusta `CANDIDATOS_LAT` / `CANDIDATOS_LON` si conoces el nombre real de esas llaves.")
        st.map(pd.DataFrame({"lat": [lat], "lon": [lon]}), zoom=10)
 
        # --- Imágenes de la estación ---
        st.subheader("Imágenes de la estación")
        st.caption("Reemplaza las rutas de abajo por tus propios archivos (por ejemplo, guárdalos en una carpeta `imagenes/` dentro del repositorio).")
        col_img1, col_img2 = st.columns(2)
        with col_img1:
            mostrar_imagen_segura("imagenes/estacion_1.jpg", "Estación de nivel — Vista 1")
        with col_img2:
            mostrar_imagen_segura("imagenes/estacion_2.jpg", "Estación de nivel — Vista 2")
 
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
