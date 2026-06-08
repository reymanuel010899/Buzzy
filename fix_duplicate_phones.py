"""
Limpia números de teléfono duplicados en la BD antes de aplicar
la migración que agrega unique=True al campo phone_number.

Estrategia: de todos los usuarios con el mismo número, conserva
el que tiene el id más bajo (el más antiguo) y pone NULL en los demás.
"""
import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Buzzy.settings")
django.setup()

from django.db import connection

with connection.cursor() as cursor:
    # Encuentra duplicados
    cursor.execute("""
        SELECT phone_number, COUNT(*) as cnt, ARRAY_AGG(id ORDER BY id) as ids
        FROM users_user
        WHERE phone_number IS NOT NULL
        GROUP BY phone_number
        HAVING COUNT(*) > 1
    """)
    duplicates = cursor.fetchall()

if not duplicates:
    print("No hay duplicados. Puedes correr la migración directamente.")
else:
    print(f"Encontrados {len(duplicates)} números duplicados. Limpiando...\n")
    with connection.cursor() as cursor:
        for phone, count, ids in duplicates:
            # El primero (menor id) se conserva, los demás se ponen a NULL
            ids_to_null = ids[1:]
            cursor.execute(
                "UPDATE users_user SET phone_number = NULL, is_phone_verified = FALSE WHERE id = ANY(%s)",
                [ids_to_null]
            )
            print(f"  {phone}: conservado id={ids[0]}, nulleados ids={ids_to_null}")

    print("\nListo. Ahora corre: python manage.py migrate")
