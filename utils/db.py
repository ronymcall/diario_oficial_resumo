import sqlite3
import json
from pathlib import Path
from config import DB_PATH
from processor.extractor import Ato


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS atos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            decreto TEXT,
            tipo TEXT,
            nome TEXT,
            cargo TEXT,
            orgao TEXT,
            data TEXT,
            edicao TEXT
        )
    """)
    colunas = {row[1] for row in conn.execute("PRAGMA table_info(atos)")}
    if "orgao" not in colunas:
        conn.execute("ALTER TABLE atos ADD COLUMN orgao TEXT")
    return conn


def salvar_atos(atos: list[Ato], edicao: str = "") -> None:
    conn = _get_conn()
    for a in atos:
        conn.execute(
            "INSERT INTO atos (decreto, tipo, nome, cargo, orgao, data, edicao) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (a.decreto, a.tipo, a.nome, a.cargo, a.orgao, a.data, edicao),
        )
    conn.commit()
    conn.close()


def carregar_atos(tipo: str = None, busca: str = None) -> list[dict]:
    conn = _get_conn()
    query = "SELECT decreto, tipo, nome, cargo, orgao, data, edicao FROM atos WHERE 1=1"
    params = []
    if tipo:
        query += " AND tipo = ?"
        params.append(tipo)
    if busca:
        query += " AND nome LIKE ?"
        params.append(f"%{busca}%")
    query += " ORDER BY id DESC"

    rows = conn.execute(query, params).fetchall()
    conn.close()

    return [
        {
            "decreto": r[0],
            "tipo": r[1],
            "nome": r[2],
            "cargo": r[3],
            "orgao": r[4],
            "data": r[5],
            "edicao": r[6],
        }
        for r in rows
    ]   
