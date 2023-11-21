import psycopg_pool
from psycopg.rows import dict_row
import os
import dotenv

from base_logger import main_logger

dotenv.load_dotenv()

conninfo = f'host={os.getenv("HOSTNAME")} port={os.getenv("PORT")} dbname={os.getenv("DATABASE")} user={os.getenv("USER")} password={os.getenv("PASSWORD")}'

pool = psycopg_pool.AsyncConnectionPool(conninfo=conninfo, open=False, min_size=4, max_size=50)

print = main_logger.info


async def open_pool():
    await pool.open()
    print("Connection Pool Opened")


async def select_fetchone(query, args=None):
    async with pool.connection() as conn:
        async with conn.cursor() as cursor:
            await cursor.execute(query, args)
            results = await cursor.fetchone()
            return results


async def select_fetchall(query, args=None):
    async with pool.connection() as conn:
        async with conn.cursor() as cursor:
            await cursor.execute(query, args)
            results = await cursor.fetchall()
            return results


async def select_fetchall_dict(query, args=None):
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cursor:
            await cursor.execute(query, args)
            results = await cursor.fetchall()
            return results


async def select_fetchone_dict(query, args=None):
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cursor:
            await cursor.execute(query, args)
            results = await cursor.fetchone()
            return results


async def write(query, args=None):
    async with pool.connection() as conn:
        async with conn.cursor() as cursor:
            await cursor.execute(query, args)
            if 'RETURNING' in query:
                results = await cursor.fetchone()
                return results
            else:
                return

