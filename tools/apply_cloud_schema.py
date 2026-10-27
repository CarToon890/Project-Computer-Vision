"""Apply additive OMR schema only to the explicitly linked database."""
import os
from pathlib import Path


def main():
    if not os.environ.get('DATABASE_URL'):
        raise SystemExit('DATABASE_URL is not configured; no migration run.')
    import psycopg
    schema = Path(__file__).resolve().parents[1] / 'apps/shared/schema.sql'
    with psycopg.connect(os.environ['DATABASE_URL'], sslmode='require') as connection:
        connection.execute(schema.read_text(encoding='utf-8'))
    print('Additive OMR schema applied successfully.')


if __name__ == '__main__':
    main()
