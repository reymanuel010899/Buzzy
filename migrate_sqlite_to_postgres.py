"""
Script para migrar datos de SQLite a PostgreSQL.

Uso:
    python migrate_sqlite_to_postgres.py

Este script:
1. Lee directamente el db.sqlite3
2. Genera SQL compatible con PostgreSQL
3. Lo importa en la base de datos Postgres configurada en .env
"""

import sqlite3
import psycopg2
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# Cargar .env manualmente
def load_env():
    env_path = BASE_DIR / '.env'
    env = {}
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                env[k.strip()] = v.strip()
    return env

env = load_env()

SQLITE_PATH = BASE_DIR / 'db.sqlite3'
PG_CONFIG = {
    'dbname': env.get('POSTGRES_DB', 'buzzy_db'),
    'user': env.get('POSTGRES_USER', 'buzzy_user'),
    'password': env.get('POSTGRES_PASSWORD', ''),
    'host': env.get('DB_HOST', 'localhost'),
    'port': env.get('DB_PORT', '5432'),
}

# Tablas a migrar en orden (respetando FK)
# Excluimos: django_migrations, django_content_type, auth_permission,
#            django_session, token_blacklist_*, django_admin_log (se regeneran)
TABLES = [
    'users_country',
    'users_user',
    'users_availability',
    'users_socialaccount',
    'users_trending',
    'users_recentsearch',
    'auth_group',
    'auth_group_permissions',
    'users_user_groups',
    'users_user_user_permissions',
    'wallet_currencymodel',
    'wallet_walletmodel',
    'wallet_bankaccount',
    'wallet_tokenpackage',
    'wallet_globalsettings',
    'wallet_transactionmodel',
    'subscriptions_subscriptionplan',
    'subscriptions_usersubscription',
    'subscriptions_subscriptionbenefit',
    'subscriptions_callsession',
    'videos_category',
    'videos_hashtag',
    'videos_video',
    'videos_videohashtag',
    'videos_view',
    'videos_like',
    'videos_comment',
    'videos_follower',
    'videos_story',
    'videos_storymedia',
    'videos_storyview',
    'videos_storylike',
    'videos_giftstory',
    'videos_storygift',
    'videos_chatroom',
    'videos_message',
    'videos_messagereaction',
    'videos_useronlinestatus',
    'videos_typingstatus',
    'videos_notification',
    'videos_aistyle',
    'videos_aitemplate',
    'videos_aigenerationhistory',
    'videos_videogift',
    'videos_videostats',
    'ads_adaudience',
    'ads_adcampaign',
    'ads_adbudget',
    'ads_adcreative',
    'ads_adanalytics',
    'ads_adimpression',
    'markerplace_category',
    'markerplace_product',
    # authtoken si existe
    'authtoken_token',
]

def get_sqlite_columns(cur, table):
    cur.execute(f"PRAGMA table_info({table})")
    return [row[1] for row in cur.fetchall()]

def get_postgres_columns(pg_cur, table):
    pg_cur.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = %s AND table_schema = 'public'
        ORDER BY ordinal_position
    """, (table,))
    return [row[0] for row in pg_cur.fetchall()]

def get_pg_boolean_cols(pg_cur, table):
    """Retorna set de columnas boolean en Postgres para una tabla."""
    pg_cur.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = %s AND table_schema = 'public'
        AND data_type = 'boolean'
    """, (table,))
    return {row[0] for row in pg_cur.fetchall()}

def get_pg_col_info(pg_cur, table):
    """Retorna dict {col: (column_default, is_nullable, char_max_length)} para todas las columnas."""
    pg_cur.execute("""
        SELECT column_name, column_default, is_nullable, character_maximum_length
        FROM information_schema.columns
        WHERE table_name = %s AND table_schema = 'public'
        ORDER BY ordinal_position
    """, (table,))
    return {row[0]: (row[1], row[2], row[3]) for row in pg_cur.fetchall()}

def migrate_table(sqlite_con, pg_con, table):
    sq_cur = sqlite_con.cursor()
    pg_cur = pg_con.cursor()

    # Verificar que la tabla existe en SQLite
    sq_cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
    if not sq_cur.fetchone():
        print(f"  ⚠️  {table}: no existe en SQLite, saltando")
        return 0

    # Verificar que existe en Postgres
    pg_cur.execute("SELECT to_regclass(%s)", (f'public.{table}',))
    if pg_cur.fetchone()[0] is None:
        print(f"  ⚠️  {table}: no existe en Postgres (¿faltan migraciones?), saltando")
        return 0

    # Columnas comunes entre SQLite y Postgres
    sq_cols = get_sqlite_columns(sq_cur, table)
    pg_cols = get_postgres_columns(pg_cur, table)

    # Columnas boolean en Postgres (SQLite las guarda como 0/1)
    bool_cols = get_pg_boolean_cols(pg_cur, table)

    # Info de defaults, nullable y max_length de todas las columnas Postgres
    pg_col_info = get_pg_col_info(pg_cur, table)

    # Límites de longitud por columna (para varchar)
    varchar_limits = {c: info[2] for c, info in pg_col_info.items() if info[2] is not None}

    # Columnas que existen en SQLite y en Postgres
    common_cols = [c for c in sq_cols if c in pg_cols]
    if not common_cols:
        print(f"  ⚠️  {table}: sin columnas en común, saltando")
        return 0

    # Columnas nuevas (solo en PG, no en SQLite) que son NOT NULL y tienen default conocido
    # Las incluimos en el INSERT con su valor default para evitar violaciones NOT NULL
    import uuid as _uuid
    KNOWN_DEFAULTS = {
        'language': 'en',
        'bonus_balance': 0,
        'blocked_amount': 0,
        'total_deposited': 0,
        'total_withdrawn': 0,
        'version': 1,
        'tokens': 0,
        'ai_generations_this_month': 0,
        'video_calls_this_month': 0,
    }
    # Para pass_code (uuid único), generamos uno único por fila luego
    UUID_COLS = {'pass_code'}
    extra_cols = []
    extra_vals = []
    for c in pg_cols:
        if c in sq_cols:
            continue  # ya está en common_cols
        col_info = pg_col_info.get(c, (None, 'YES', None))
        default_val, is_nullable = col_info[0], col_info[1]
        if is_nullable == 'NO' and default_val is None:
            # Necesita un valor; buscar en KNOWN_DEFAULTS primero
            if c in KNOWN_DEFAULTS:
                extra_cols.append(c)
                extra_vals.append(KNOWN_DEFAULTS[c])
            elif c in UUID_COLS:
                # Placeholder; lo generamos por fila en convert_row
                extra_cols.append(c)
                extra_vals.append('__UUID__')
        # Si tiene default de postgres (ej: nextval, 'en'::varchar), lo omitimos
        # y dejamos que Postgres lo ponga solo

    bool_col_indices = {i for i, c in enumerate(common_cols) if c in bool_cols}
    # También verificar índices de extra_cols que sean boolean
    extra_bool_indices = {len(common_cols) + i for i, c in enumerate(extra_cols) if c in bool_cols}
    bool_col_indices |= extra_bool_indices

    all_insert_cols = common_cols + extra_cols

    sq_cur.execute(f"SELECT {','.join(common_cols)} FROM {table}")
    rows = sq_cur.fetchall()

    if not rows:
        print(f"  ℹ️  {table}: vacía")
        return 0

    # Limpiar tabla en Postgres antes de insertar
    try:
        pg_cur.execute(f"TRUNCATE TABLE \"{table}\" RESTART IDENTITY CASCADE")
    except Exception as e:
        pg_con.rollback()
        print(f"  ❌ {table}: error al limpiar: {e}")
        return 0

    cols_str = ', '.join(f'"{c}"' for c in all_insert_cols)
    placeholders = ', '.join(['%s'] * len(all_insert_cols))
    insert_sql = f'INSERT INTO "{table}" ({cols_str}) VALUES ({placeholders}) ON CONFLICT DO NOTHING'

    def convert_row(row):
        # Combinar valores de SQLite + valores extra para columnas nuevas
        row_extra = [str(_uuid.uuid4()) if v == '__UUID__' else v for v in extra_vals]
        all_vals = list(row) + row_extra
        result = []
        for i, v in enumerate(all_vals):
            col_name = all_insert_cols[i]
            if i in bool_col_indices and v is not None:
                result.append(bool(v))
            elif isinstance(v, str) and col_name in varchar_limits:
                limit = varchar_limits[col_name]
                result.append(v[:limit] if len(v) > limit else v)
            else:
                result.append(v)
        return tuple(result)

    errors = 0
    inserted = 0
    for row in rows:
        values = convert_row(row)
        try:
            pg_cur.execute(insert_sql, values)
            inserted += 1
        except Exception as e:
            pg_con.rollback()
            print(f"  ⚠️  {table}: fila saltada ({e}) - valores: {values[:3]}...")
            errors += 1
            # Reiniciar cursor tras rollback parcial
            pg_cur = pg_con.cursor()

    pg_con.commit()

    skipped_cols = [c for c in pg_cols if c not in sq_cols and c not in extra_cols]
    msg = f"  ✅ {table}: {inserted} filas"
    if skipped_cols:
        msg += f" (cols nuevas con default: {', '.join(skipped_cols)})"
    if errors:
        msg += f" ({errors} errores)"
    print(msg)
    return inserted

def reset_sequences(pg_con):
    """Resetea las secuencias de auto-incremento de Postgres para que no choquen."""
    pg_cur = pg_con.cursor()
    pg_cur.execute("""
        SELECT schemaname, tablename, attname, seqname
        FROM pg_sequences s
        JOIN pg_attribute a ON a.attrelid = (
            SELECT oid FROM pg_class WHERE relname = s.sequencename
        ) ON TRUE
        WHERE schemaname = 'public'
    """)
    # Método más simple: resetear todas las secuencias de las tablas migradas
    pg_cur.execute("""
        SELECT sequence_name FROM information_schema.sequences
        WHERE sequence_schema = 'public'
    """)
    sequences = [row[0] for row in pg_cur.fetchall()]

    for seq in sequences:
        # Extraer nombre de tabla de la secuencia (patrón: tablename_colname_seq)
        try:
            # Formato típico: videos_video_id_seq → tabla: videos_video, col: id
            parts = seq.rsplit('_', 2)
            if len(parts) >= 3:
                table = '_'.join(parts[:-2])
                col = parts[-2]
                pg_cur.execute(f"""
                    SELECT setval('{seq}', COALESCE((SELECT MAX("{col}") FROM "{table}"), 1))
                """)
        except Exception:
            pass

    pg_con.commit()
    print(f"\n  ✅ Secuencias reseteadas ({len(sequences)} secuencias)")

def main():
    print("=" * 60)
    print("  Migración SQLite → PostgreSQL")
    print("=" * 60)
    print(f"\nFuente: {SQLITE_PATH}")
    print(f"Destino: {PG_CONFIG['dbname']}@{PG_CONFIG['host']}\n")

    if not SQLITE_PATH.exists():
        print("❌ No se encontró db.sqlite3")
        sys.exit(1)

    try:
        sqlite_con = sqlite3.connect(str(SQLITE_PATH))
        sqlite_con.row_factory = sqlite3.Row
    except Exception as e:
        print(f"❌ Error abriendo SQLite: {e}")
        sys.exit(1)

    try:
        pg_con = psycopg2.connect(**PG_CONFIG)
        pg_con.autocommit = False
    except Exception as e:
        print(f"❌ Error conectando a PostgreSQL: {e}")
        print("  Verifica que PostgreSQL está corriendo y las credenciales en .env son correctas")
        sys.exit(1)

    print("Conexiones establecidas ✅\n")
    print("Migrando tablas...\n")

    total = 0
    for table in TABLES:
        count = migrate_table(sqlite_con, pg_con, table)
        total += count

    print(f"\n{'=' * 60}")
    print("Reseteando secuencias...")
    reset_sequences(pg_con)

    print(f"\n{'=' * 60}")
    print(f"✅ Migración completada: {total} filas en total")
    print(f"{'=' * 60}\n")

    sqlite_con.close()
    pg_con.close()

if __name__ == '__main__':
    main()
