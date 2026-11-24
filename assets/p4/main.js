async function inicializar() {
  const urlConfig = document.body.dataset.api;
  const respuesta = await fetch(urlConfig);
  const config = await respuesta.json();

  const datos = config.datosPersonales;
  const ubicacion = config.ubicacion;

  document.title = datos.nombre + " · Práctica 4";

  const coordenadas = [ubicacion.lat, ubicacion.lng];

  const mapa = L.map("mapa-leaflet").setView(coordenadas, ubicacion.zoom || 15);

  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "© OpenStreetMap contributors",
  }).addTo(mapa);

  L.marker(coordenadas)
    .addTo(mapa)
    .bindPopup(ubicacion.etiqueta)
    .openPopup();
}

inicializar();
