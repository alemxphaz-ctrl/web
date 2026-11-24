// Práctica 9 · Mapa de sucursales con Leaflet y OpenStreetMap.
// La sucursal principal y sus coordenadas vienen del servidor.

const contenedorMapa = document.getElementById('mapa-sucursales');

if (contenedorMapa && typeof L !== 'undefined') {
    let sucursales = [];

    try {
        sucursales = JSON.parse(contenedorMapa.dataset.sucursales || '[]');
    } catch (error) {
        sucursales = [];
    }

    const centro = [19.645, -99.16944];
    const mapa = L.map(contenedorMapa).setView(centro, 12);

    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19,
        attribution: '© OpenStreetMap contributors',
    }).addTo(mapa);

    const grupo = L.featureGroup();

    sucursales.forEach((sucursal) => {
        const popup = document.createElement('div');
        popup.className = 'popup-sucursal';

        const titulo = document.createElement('strong');
        titulo.textContent = sucursal.nombre;

        const direccion = document.createElement('p');
        direccion.textContent = sucursal.direccion;

        const horario = document.createElement('small');
        horario.textContent = `Horario: ${sucursal.horario}`;

        popup.append(titulo, direccion, horario);

        const marcador = L.marker([sucursal.lat, sucursal.lng]);
        marcador.bindPopup(popup);
        marcador.addTo(grupo);
    });

    grupo.addTo(mapa);

    if (sucursales.length > 0) {
        mapa.fitBounds(grupo.getBounds().pad(0.25));
    }
}
