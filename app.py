import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import pydeck as pdk
from pathlib import Path
from datetime import date

# ============================================================
# COPAG | Dashboard logistique
# Lancement : streamlit run app.py
# Identifiants de démonstration : admin / copag2025
# ============================================================

st.set_page_config(
    page_title="COPAG | Pilotage logistique",
    page_icon="🚚",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Palette et style
NAVY = "#12304A"
TEAL = "#16A6A1"
ORANGE = "#F2A541"
BG = "#F4F7FB"

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&display=swap');
    html, body, [class*="css"] { font-family: 'Manrope', sans-serif; }
    .stApp { background: #F4F7FB; }
    section[data-testid="stSidebar"] { background: #102B43; }
    section[data-testid="stSidebar"] * { color: #F4F8FC !important; }
    .hero {
        background: linear-gradient(110deg, #12304A 0%, #176B75 100%);
        padding: 25px 30px; border-radius: 18px; color: white;
        margin-bottom: 18px; box-shadow: 0 8px 24px rgba(18,48,74,.12);
    }
    .hero h1 { color: white; margin: 0; font-size: 29px; font-weight: 800; }
    .hero p { color: #D8E8EF; margin: 7px 0 0 0; }
    div[data-testid="stMetric"] {
        background: white; padding: 17px 18px; border-radius: 15px;
        border: 1px solid #E7EDF3; box-shadow: 0 3px 12px rgba(20,45,70,.04);
    }
    div[data-testid="stMetricLabel"] { color: #63778A; font-weight: 600; }
    div[data-testid="stMetricValue"] { color: #12304A; font-weight: 800; }
    .section-title { color: #12304A; font-size: 20px; font-weight: 800; margin: 12px 0 4px; }
    .hint { color: #718096; font-size: 12px; }
    .login-wrap { max-width: 470px; margin: 8vh auto 0 auto; }
    div.stButton > button { border-radius: 10px; font-weight: 700; }
</style>
""", unsafe_allow_html=True)

# ---------------------- Authentification ----------------------
def login():
    st.markdown('<div class="login-wrap">', unsafe_allow_html=True)
    st.markdown("""
    <div class="hero">
      <h1>🚚 COPAG Logistics</h1>
      <p>Plateforme de pilotage des opérations de transport</p>
    </div>
    """, unsafe_allow_html=True)
    with st.form("login_form"):
        st.subheader("Connexion à votre espace")
        username = st.text_input("Nom d'utilisateur", placeholder="admin")
        password = st.text_input("Mot de passe", type="password", placeholder="••••••••")
        submitted = st.form_submit_button("Se connecter", use_container_width=True)
        if submitted:
            # Démonstration uniquement : remplacer par une authentification sécurisée
            # (hash des mots de passe / SSO / base utilisateurs) en production.
            if username == "admin" and password == "copag2025":
                st.session_state["authenticated"] = True
                st.session_state["username"] = username
                st.rerun()
            else:
                st.error("Identifiants incorrects. Veuillez réessayer.")
    st.caption("Accès de démonstration : admin / copag2025")
    st.markdown("</div>", unsafe_allow_html=True)

if not st.session_state.get("authenticated", False):
    login()
    st.stop()

# ---------------------- Chargement & nettoyage ----------------------
@st.cache_data
def load_data(file_bytes=None):
    if file_bytes:
        from io import BytesIO
        data = pd.read_csv(BytesIO(file_bytes))
    else:
        data_path = Path(__file__).parent / "data" / "dataset.csv"
        if not data_path.exists():
            data_path = Path(__file__).parent / "dataset.csv"
        data = pd.read_csv(data_path)

    data.columns = data.columns.str.strip()
    if "date" in data.columns:
        data["date"] = pd.to_datetime(data["date"], errors="coerce")
    numeric_cols = data.select_dtypes(include=np.number).columns
    for col in numeric_cols:
        data[col] = pd.to_numeric(data[col], errors="coerce")

    # Suppression des doublons d'expédition
    if "shipment_id" in data.columns:
        data = data.drop_duplicates(subset=["shipment_id"], keep="first")
    else:
        data = data.drop_duplicates()

    # Valeurs physiques impossibles : remplacées par NaN, sans inventer de valeurs
    non_negative = [
        "distance_km", "planned_duration_min", "actual_duration_min",
        "delay_min", "fuel_liters", "co2_kg", "cost_mad", "quantity_tons"
    ]
    for col in non_negative:
        if col in data.columns:
            data.loc[data[col] < 0, col] = np.nan

    for col in ["on_time", "temperature_breach"]:
        if col in data.columns:
            data.loc[~data[col].isin([0, 1]), col] = np.nan

    # Champs dérivés utiles au pilotage
    if {"origin_hub", "destination_city"}.issubset(data.columns):
        data["lane"] = data["origin_hub"].astype(str) + " → " + data["destination_city"].astype(str)
    if {"cost_mad", "distance_km"}.issubset(data.columns):
        data["cost_per_km"] = data["cost_mad"] / data["distance_km"].replace(0, np.nan)
    if {"fuel_liters", "distance_km"}.issubset(data.columns):
        data["fuel_per_100km"] = 100 * data["fuel_liters"] / data["distance_km"].replace(0, np.nan)
    return data

st.sidebar.markdown("## 🚚 COPAG")
st.sidebar.caption("Pilotage de la performance logistique")
if st.sidebar.button("Déconnexion", use_container_width=True):
    st.session_state.clear()
    st.rerun()

uploaded = st.sidebar.file_uploader("Importer un autre fichier CSV", type=["csv"])
df = load_data(uploaded.getvalue() if uploaded else None)

# ---------------------- Filtres ----------------------
st.sidebar.markdown("---")
st.sidebar.markdown("### 🔎 Filtres")
filtered = df.copy()

def add_select_filter(label, column):
    global filtered
    if column in filtered.columns:
        options = sorted(filtered[column].dropna().astype(str).unique().tolist())
        selected = st.sidebar.selectbox(label, ["Toutes"] + options)
        if selected != "Toutes":
            filtered = filtered[filtered[column].astype(str) == selected]

add_select_filter("Région de destination", "destination_region")
add_select_filter("Mode de transport", "mode")
add_select_filter("Catégorie de produit", "product_category")

if "date" in filtered.columns and filtered["date"].notna().any():
    min_date = filtered["date"].min().date()
    max_date = filtered["date"].max().date()
    date_range = st.sidebar.date_input(
        "Période", value=(min_date, max_date), min_value=min_date, max_value=max_date
    )
    if isinstance(date_range, tuple) and len(date_range) == 2:
        start_date, end_date = date_range
        filtered = filtered[filtered["date"].dt.date.between(start_date, end_date)]

# ---------------------- En-tête ----------------------
st.markdown("""
<div class="hero">
  <h1>Tableau de bord logistique COPAG</h1>
  <p>Analyse des livraisons, des coûts, de la consommation énergétique et des flux au Maroc</p>
</div>
""", unsafe_allow_html=True)

if filtered.empty:
    st.warning("Aucune expédition ne correspond aux filtres sélectionnés.")
    st.stop()

# ---------------------- KPI ----------------------
st.markdown('<div class="section-title">Indicateurs clés de performance</div>', unsafe_allow_html=True)
def mean_col(col):
    return filtered[col].mean() if col in filtered.columns and filtered[col].notna().any() else np.nan

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("🚚 Livraisons", f"{len(filtered):,}".replace(",", " "))
on_time = mean_col("on_time")
k2.metric("⏱️ À l'heure", f"{on_time*100:.1f} %" if pd.notna(on_time) else "—")
k3.metric("💰 Coût moyen", f"{mean_col('cost_mad'):,.0f} MAD" if pd.notna(mean_col("cost_mad")) else "—")
k4.metric("⛽ Carburant / trajet", f"{mean_col('fuel_liters'):.1f} L" if pd.notna(mean_col("fuel_liters")) else "—")
k5.metric("🌱 CO₂ / trajet", f"{mean_col('co2_kg'):.1f} kg" if pd.notna(mean_col("co2_kg")) else "—")

st.markdown('<div class="hint">Les indicateurs sont recalculés selon les filtres actifs.</div>', unsafe_allow_html=True)
st.markdown("---")

sns.set_theme(style="whitegrid", palette="deep")
left, right = st.columns(2)

# 1. Performance quotidienne
with left:
    st.markdown("**1. Performance quotidienne – On-Time Rate**")
    if {"date", "on_time"}.issubset(filtered.columns):
        daily = filtered.dropna(subset=["date", "on_time"]).groupby("date")["on_time"].mean().mul(100)
        fig, ax = plt.subplots(figsize=(7, 3.4))
        ax.plot(daily.index, daily.values, marker="o", linewidth=2, color=TEAL)
        ax.set_ylabel("Livraisons à l'heure (%)")
        ax.set_xlabel("Date")
        ax.set_ylim(0, 105)
        fig.tight_layout()
        st.pyplot(fig)
        plt.close(fig)
    else:
        st.info("Colonnes date / on_time indisponibles.")

# 2. Top 10 routes
with right:
    st.markdown("**2. Top 10 des itinéraires par volume**")
    if "lane" in filtered.columns:
        top = filtered["lane"].value_counts().head(10).sort_values()
        fig, ax = plt.subplots(figsize=(7, 3.4))
        sns.barplot(x=top.values, y=top.index, ax=ax, color=TEAL)
        ax.set_xlabel("Nombre de livraisons")
        ax.set_ylabel("Itinéraire")
        fig.tight_layout()
        st.pyplot(fig)
        plt.close(fig)

left, right = st.columns(2)

# 3. Retards par produit
with left:
    st.markdown("**3. Distribution des retards par produit**")
    if {"product_category", "delay_min"}.issubset(filtered.columns):
        fig, ax = plt.subplots(figsize=(7, 3.5))
        sns.boxplot(data=filtered, x="delay_min", y="product_category", ax=ax, color="#8CCBC7")
        ax.set_xlabel("Retard (minutes)")
        ax.set_ylabel("Catégorie de produit")
        fig.tight_layout()
        st.pyplot(fig)
        plt.close(fig)

# 4. Corrélations
with right:
    st.markdown("**4. Matrice de corrélation**")
    numeric = filtered.select_dtypes(include=np.number)
    corr_cols = [c for c in ["distance_km", "planned_duration_min", "actual_duration_min",
                              "delay_min", "fuel_liters", "co2_kg", "cost_mad",
                              "quantity_tons", "capacity_utilization"] if c in numeric.columns]
    if len(corr_cols) >= 2:
        fig, ax = plt.subplots(figsize=(7, 3.8))
        sns.heatmap(numeric[corr_cols].corr(), annot=True, fmt=".2f", cmap="YlGnBu",
                    linewidths=.5, ax=ax, cbar=False)
        fig.tight_layout()
        st.pyplot(fig)
        plt.close(fig)
    else:
        st.info("Pas assez de variables numériques.")

left, right = st.columns(2)

# 5. Coût par km / région
with left:
    st.markdown("**5. Coût moyen par kilomètre et par région**")
    if {"destination_region", "cost_per_km"}.issubset(filtered.columns):
        region_cost = filtered.groupby("destination_region")["cost_per_km"].mean().dropna().sort_values()
        fig, ax = plt.subplots(figsize=(7, 3.5))
        ax.barh(region_cost.index, region_cost.values, color=ORANGE)
        ax.set_xlabel("MAD / km")
        ax.set_ylabel("Région")
        fig.tight_layout()
        st.pyplot(fig)
        plt.close(fig)

# 6. Part des expéditions par produit
with right:
    st.markdown("**6. Répartition des expéditions par produit**")
    if "product_category" in filtered.columns:
        product_counts = filtered["product_category"].value_counts()
        fig, ax = plt.subplots(figsize=(7, 3.5))
        ax.pie(product_counts.values, labels=product_counts.index, autopct="%1.1f%%",
               startangle=90, textprops={"fontsize": 8})
        ax.axis("equal")
        fig.tight_layout()
        st.pyplot(fig)
        plt.close(fig)

left, right = st.columns(2)

# 7. Distribution des coûts
with left:
    st.markdown("**7. Distribution des coûts de transport**")
    if "cost_mad" in filtered.columns:
        fig, ax = plt.subplots(figsize=(7, 3.4))
        sns.histplot(filtered["cost_mad"].dropna(), kde=True, ax=ax, color=TEAL)
        ax.set_xlabel("Coût (MAD)")
        ax.set_ylabel("Nombre d'expéditions")
        fig.tight_layout()
        st.pyplot(fig)
        plt.close(fig)

# 8. Carburant selon distance
with right:
    st.markdown("**8. Carburant consommé selon la distance**")
    if {"distance_km", "fuel_liters"}.issubset(filtered.columns):
        fig, ax = plt.subplots(figsize=(7, 3.4))
        sns.scatterplot(data=filtered, x="distance_km", y="fuel_liters",
                        hue="mode" if "mode" in filtered.columns else None,
                        alpha=.7, ax=ax)
        ax.set_xlabel("Distance (km)")
        ax.set_ylabel("Carburant (L)")
        fig.tight_layout()
        st.pyplot(fig)
        plt.close(fig)

# ---------------------- Cartes ----------------------
st.markdown("---")
st.markdown('<div class="section-title">Cartographie des opérations</div>', unsafe_allow_html=True)
map_left, map_right = st.columns(2)

with map_left:
    st.markdown("**9. Positions de la flotte**")
    if {"lat", "lon"}.issubset(filtered.columns):
        fleet = filtered.dropna(subset=["lat", "lon"])[["lat", "lon"]].rename(
            columns={"lat": "latitude", "lon": "longitude"}
        )
        fleet = fleet[fleet["latitude"].between(-90, 90) & fleet["longitude"].between(-180, 180)]
        if not fleet.empty:
            st.map(fleet, latitude="latitude", longitude="longitude", size=30)
        else:
            st.info("Aucune coordonnée de camion disponible.")
    else:
        st.info("Colonnes lat / lon indisponibles.")

with map_right:
    st.markdown("**10. Flux entre hubs et villes – ArcLayer**")
    route_cols = ["o_lat", "o_lon", "d_lat", "d_lon"]
    if all(c in filtered.columns for c in route_cols):
        routes = filtered.dropna(subset=route_cols).copy()
        if not routes.empty:
            routes = routes.groupby(["o_lat", "o_lon", "d_lat", "d_lon"], as_index=False).size()
            routes = routes.rename(columns={"size": "count"})
            layer = pdk.Layer(
                "ArcLayer", data=routes, get_source_position=["o_lon", "o_lat"],
                get_target_position=["d_lon", "d_lat"], get_source_color=[22, 166, 161],
                get_target_color=[242, 165, 65], get_width="count * 1.5",
                pickable=True, auto_highlight=True
            )
            view = pdk.ViewState(
                latitude=float(routes[["o_lat", "d_lat"]].to_numpy().mean()),
                longitude=float(routes[["o_lon", "d_lon"]].to_numpy().mean()),
                zoom=4.2, pitch=35
            )
            st.pydeck_chart(pdk.Deck(
                layers=[layer], initial_view_state=view,
                tooltip={"text": "Nombre de trajets : {count}"}
            ), use_container_width=True)
        else:
            st.info("Aucun flux géographique disponible.")
    else:
        st.info("Coordonnées origine / destination indisponibles.")

# ---------------------- Interprétation ----------------------
st.markdown("---")
st.markdown('<div class="section-title">Synthèse automatique</div>', unsafe_allow_html=True)
summary = []
if pd.notna(on_time):
    summary.append(f"Le taux de livraisons à l'heure est de **{on_time*100:.1f} %**.")
if "delay_min" in filtered.columns and filtered["delay_min"].notna().any():
    summary.append(f"Le retard moyen observé est de **{filtered['delay_min'].mean():.1f} minutes**.")
if "destination_region" in filtered.columns and "cost_per_km" in filtered.columns:
    rc = filtered.groupby("destination_region")["cost_per_km"].mean().dropna()
    if not rc.empty:
        summary.append(f"La région présentant le coût moyen au kilomètre le plus élevé est **{rc.idxmax()}** ({rc.max():.2f} MAD/km).")
if "lane" in filtered.columns and not filtered["lane"].value_counts().empty:
    summary.append(f"L'itinéraire le plus fréquent est **{filtered['lane'].value_counts().idxmax()}**.")
if "temperature_breach" in filtered.columns:
    breaches = filtered["temperature_breach"].fillna(0).sum()
    summary.append(f"Ruptures de chaîne du froid enregistrées : **{int(breaches)}**.")
for item in summary:
    st.markdown("- " + item)

with st.expander("Aperçu des données nettoyées"):
    st.caption(f"{len(df)} expéditions après suppression des doublons | {len(filtered)} après filtres")
    st.dataframe(filtered, use_container_width=True, height=320)
    st.download_button(
        "Télécharger les données filtrées (CSV)",
        filtered.to_csv(index=False).encode("utf-8-sig"),
        file_name="copag_donnees_filtrees.csv",
        mime="text/csv"
    )

with st.expander("Qualité et nettoyage des données"):
    st.write("Le traitement convertit les dates et colonnes numériques, supprime les doublons d'expédition et invalide les valeurs négatives pour les mesures physiques.")
    quality = pd.DataFrame({
        "Valeurs manquantes": df.isna().sum(),
        "Taux manquant (%)": (df.isna().mean() * 100).round(2)
    })
    st.dataframe(quality, use_container_width=True)

st.caption("COPAG Logistics • Outil pédagogique de pilotage • Données fournies pour le projet")
