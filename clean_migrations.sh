#!/bin/bash

echo "🚀 Iniciando limpieza de migraciones en Buzzy Proyect..."

# 1. Borrar archivos físicos de migraciones (excepto __init__.py)
find . -path "*/migrations/*.py" -not -name "__init__.py" -delete
find . -path "*/migrations/*.pyc" -delete

echo "✅ Archivos .py de migraciones eliminados (excepto __init__.py)."

# 2. Resetear la base de datos de Django (Opcional pero recomendado tras un KeyError)
# Esto limpia la tabla interna de Django para que no busque registros viejos
read -p "⚠️ ¿Quieres limpiar el historial de la DB en Postgres? (s/n): " resp
if [ "$resp" = "s" ]; then
    python3 manage.py dbshell <<EOF
TRUNCATE django_migrations;
EOF
    echo "✅ Historial de migraciones truncado en la base de datos."
fi

# 3. Regenerar migraciones limpias
echo "📦 Generando nuevas migraciones..."
python3 manage.py makemigrations

echo "🎉 ¡Listo! Ahora puedes ejecutar 'python3 manage.py migrate --fake-initial'"