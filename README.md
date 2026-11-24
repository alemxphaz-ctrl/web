# Pascual · Prácticas 3 a 9

Sitio de prácticas web implementado con Python y Flask. Las plantillas HTML,
estilos, JavaScript, fotos y videos se conservan como recursos de interfaz;
las rutas y la lógica de las prácticas se ejecutan en Python. Los datos se
guardan localmente con SQLite, incluido con Python.

## Requisitos

- Python 3.10 o posterior.
- Visual Studio Code.

## Ejecutar en Windows

Abre la carpeta `web_general` en VS Code. En la terminal integrada
(`Terminal > Nueva terminal`), crea el entorno e instala las dependencias:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Después, inicia el servidor desde `Terminal > Ejecutar tarea...` y selecciona
`Iniciar prácticas (Flask)`. También puedes ejecutarlo manualmente:

```powershell
.\.venv\Scripts\python.exe app.py
```

Abre <http://127.0.0.1:8000>. La base de datos se crea automáticamente en
`data/pascual.sqlite3` al entrar por primera vez y se conserva entre ejecuciones.
Puedes cambiar su ubicación definiendo la variable de entorno `DB_PATH`.

## Prácticas y rutas

- `/` — Menú de prácticas.
- `/p3` — CRUD de productos.
- `/p4` — Perfil, ruta estática desde la UPVM y mapa interactivo de Tultitlán.
- `/p5` — Inicio de sesión, registro y CRUD de estudiantes.
- `/p6` — Encuesta de satisfacción.
- `/p7` — Video HTML5.
- `/p8` — Rastreador y panel de métricas JSON.
- `/p9` — Tienda Pimpz, catálogo de ejemplo, chat, sucursal y administración.

El chat requiere una cuenta de la práctica 5. El acceso de ejemplo del panel
administrativo de la práctica 9 es matrícula `777` y contraseña `admin`.

## Despliegue (Render + Aiven PostgreSQL)

1. En Aiven crea un servicio **PostgreSQL** (plan Free) y copia su **Service URI**.
2. En Render usa **New → Blueprint** con este repositorio (lee `render.yaml`).
3. Cuando Render pida `DATABASE_URL`, pega la Service URI de Aiven.

Si `DATABASE_URL` empieza con `postgres://` se usa PostgreSQL; si no existe,
se usa SQLite local. Las tablas se crean solas en el primer acceso.

## Archivos principales

- `app.py` — rutas Flask, sesiones, validaciones y consultas SQLite.
- `templates/` — páginas HTML renderizadas por Flask.
- `assets/` — CSS, JavaScript, imágenes, mapas y videos.
- `requirements.txt` — dependencias Python.
